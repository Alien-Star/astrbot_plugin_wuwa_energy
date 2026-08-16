"""API 客户端离线测试：用假 session 验证 Token 认证、体力查询解析。

运行：python tests/test_client.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot_plugin_wuwa_energy.kuro_client import KuroAPIError, KuroAuthError, KuroBBSClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return self._payload


class FakeSession:
    closed = False

    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.calls = []

    def post(self, url, data=None, headers=None):
        path = url.split("api.kurobbs.com")[-1]
        self.calls.append(path)
        seq = self.routes.get(path)
        return FakeResponse(seq.pop(0) if seq else {"code": 404, "msg": "not found"})


def make_client(session):
    c = KuroBBSClient()
    c._session = session
    return c


def test_get_user_info():
    ok = {"code": 200, "data": {"mine": {"userId": 10086, "userName": "小明"}}}
    c = make_client(FakeSession({"/user/mineV2": [ok]}))
    info = asyncio.run(c.get_user_info("10086", "tk1"))
    assert info.uid == "10086"
    assert info.user_name == "小明"


def test_token_expired():
    c = make_client(FakeSession({"/user/mineV2": [{"code": 220, "msg": "登录已过期"}]}))
    try:
        asyncio.run(c.get_user_info("10086", "bad"))
        assert False
    except KuroAuthError:
        pass


def test_query_energy():
    ok = {"code": 200, "data": {
        "serverTime": 1719475326,
        "energyData": {"cur": 0, "total": 240, "refreshTimeStamp": 1719508373},
    }}
    c = make_client(FakeSession({"/gamer/widget/game3/refresh": [ok]}))
    energy = asyncio.run(c.query_energy({"token": "t", "roleId": "r", "serverId": "s"}))
    assert energy.remain == 0
    assert energy.max == 240
    assert energy.total_second == 33047  # 1719508373 - 1719475326


def test_query_energy_full():
    ok = {"code": 200, "data": {"serverTime": 100, "energyData": {"cur": 240, "total": 240, "refreshTimeStamp": 0}}}
    c = make_client(FakeSession({"/gamer/widget/game3/refresh": [ok]}))
    energy = asyncio.run(c.query_energy({"token": "t", "roleId": "r", "serverId": "s"}))
    assert energy.remain == 240
    assert energy.total_second == 0


def test_energy_auth_error():
    c = make_client(FakeSession({"/gamer/widget/game3/refresh": [{"code": 220, "msg": "登录已过期"}]}))
    try:
        asyncio.run(c.query_energy({"token": "t", "roleId": "r", "serverId": "s"}))
        assert False
    except KuroAuthError:
        pass


if __name__ == "__main__":
    test_get_user_info()
    test_token_expired()
    test_query_energy()
    test_query_energy_full()
    test_energy_auth_error()
    print("客户端测试全部通过")
