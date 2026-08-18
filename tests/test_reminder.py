"""提醒逻辑集成测试：不依赖网络，用假客户端/上下文验证 @ 提醒、冷却逻辑与 Token 失效处理。

逻辑：体力 >= 阈值 时提醒（快去清体力），低于阈值不提醒。
运行：python tests/test_reminder.py
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot.api.message_components import At

from astrbot_plugin_wuwa_energy.kuro_client import EnergyInfo, KuroAuthError, KuroAPIError
from astrbot_plugin_wuwa_energy.main import WuwaEnergyPlugin


class FakeClient:
    def __init__(self, energy: EnergyInfo, raise_auth=False):
        self.energy = energy
        self.raise_auth = raise_auth
        self.query_calls = 0

    async def query_energy(self, record):
        self.query_calls += 1
        if self.raise_auth:
            raise KuroAuthError("token 已失效")
        return self.energy


class FakeContext:
    def __init__(self):
        self.sent = []

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))
        return True


def make_plugin(users, config=None):
    p = WuwaEnergyPlugin.__new__(WuwaEnergyPlugin)
    p.name = "astrbot_plugin_wuwa_energy"
    p.config = {
        "enable_reminder": True,
        "check_interval_minutes": 10,
        "remind_cooldown_minutes": 120,
        "default_threshold": 230,
        "remind_message_template": "体力 {remain}/{max} 快满了！",
    }
    if config:
        p.config.update(config)
    p._users = users
    return p


def base_user(**overrides):
    rec = {
        "qq": "10001",
        "nickname": "小明",
        "token": "t",
        "uid": "1",
        "playerId": "p1",
        "serverId": "s1",
        "roleId": "r1",
        "umo": "aiocqhttp:group:123",
        "threshold": 230,
        "last_remind_ts": 0,
    }
    rec.update(overrides)
    return rec


def test_remind_when_high():
    """体力 >= 阈值 时应发送提醒。"""
    ctx = FakeContext()
    p = make_plugin({"10001": base_user()})
    p.context = ctx
    p.client = FakeClient(EnergyInfo(remain=235, max=240, total_second=3600))

    asyncio.run(p._check_reminders())

    assert len(ctx.sent) == 1, "体力达到阈值时应发送提醒"
    umo, chain = ctx.sent[0]
    assert umo == "aiocqhttp:group:123"
    assert isinstance(chain.chain[0], At), "提醒应包含 At 组件"
    assert str(chain.chain[0].qq) == "10001"
    assert "235/240" in chain.chain[1].text
    assert p._users["10001"]["last_remind_ts"] > 0


def test_no_remind_when_low():
    """体力 < 阈值 时不提醒。"""
    ctx = FakeContext()
    p = make_plugin({"10001": base_user()})
    p.context = ctx
    p.client = FakeClient(EnergyInfo(remain=30, max=240, total_second=0))

    asyncio.run(p._check_reminders())

    assert ctx.sent == [], "体力低于阈值时不应提醒"


def test_remind_at_exact_threshold():
    """体力恰好等于阈值时应提醒。"""
    ctx = FakeContext()
    p = make_plugin({"10001": base_user()})
    p.context = ctx
    p.client = FakeClient(EnergyInfo(remain=230, max=240, total_second=0))

    asyncio.run(p._check_reminders())

    assert len(ctx.sent) == 1, "体力等于阈值时应提醒"


def test_cooldown():
    """冷却期内不应重复提醒。"""
    ctx = FakeContext()
    now = time.time()
    p = make_plugin({"10001": base_user(last_remind_ts=now - 60)})  # 1 分钟前刚提醒过
    p.context = ctx
    p.client = FakeClient(EnergyInfo(remain=235, max=240))

    asyncio.run(p._check_reminders())

    assert ctx.sent == [], "冷却期内不应重复提醒"


def test_threshold_disabled():
    """阈值为 0 时不提醒。"""
    ctx = FakeContext()
    p = make_plugin({"10001": base_user(threshold=0)})
    p.context = ctx
    p.client = FakeClient(EnergyInfo(remain=240, max=240))

    asyncio.run(p._check_reminders())

    assert ctx.sent == []


def test_token_expired_skips_without_crash():
    """Token 失效时跳过提醒且不中断其它用户的检查。"""
    ctx = FakeContext()
    p = make_plugin(
        {
            "10001": base_user(),  # token 失效
            "10002": base_user(qq="10002", nickname="小红", umo="aiocqhttp:group:123"),
        }
    )
    p.context = ctx
    p.client = FakeClient(EnergyInfo(remain=235, max=240), raise_auth=True)

    asyncio.run(p._check_reminders())  # 不应抛异常

    assert ctx.sent == []
    assert p.client.query_calls == 2, "两个用户都应被检查"


if __name__ == "__main__":
    test_remind_when_high()
    test_no_remind_when_low()
    test_remind_at_exact_threshold()
    test_cooldown()
    test_threshold_disabled()
    test_token_expired_skips_without_crash()
    print("提醒逻辑测试全部通过")
