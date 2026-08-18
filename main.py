import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star

from .kuro_client import EnergyInfo, KuroAPIError, KuroAuthError, KuroBBSClient

PLUGIN_NAME = "astrbot_plugin_wuwa_energy"


class WuwaEnergyPlugin(Star):
    """鸣潮体力助手：通过库街区 Token 认证查询鸣潮体力，体力低于阈值时在群内 @ 提醒。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.client = KuroBBSClient(
            api_base=str(config.get("api_base", "https://api.kurobbs.com")),
        )
        self._reminder_task: Optional[asyncio.Task] = None
        self._hourly_task: Optional[asyncio.Task] = None
        self._users: dict[str, dict] = {}

    async def initialize(self):
        await self._load_data()
        self._reminder_task = asyncio.create_task(self._reminder_loop())
        self._hourly_task = asyncio.create_task(self._hourly_refresh_loop())
        logger.info("鸣潮体力助手已启动（提醒任务 + 整点刷新任务）")

    async def terminate(self):
        for task in (self._reminder_task, self._hourly_task):
            if task:
                task.cancel()
        self._reminder_task = None
        self._hourly_task = None
        await self._save_data()
        await self.client.close()

    # ------------------------------------------------------------------
    # 数据持久化
    # ------------------------------------------------------------------
    def _get_data_file(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        p = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p / "users.json"

    async def _load_data(self):
        path = self._get_data_file()

        def _read():
            if not path.exists():
                return {}
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except Exception as e:
                logger.error(f"读取绑定数据失败: {e}")
                return {}

        self._users = await asyncio.to_thread(_read)
        logger.info(f"已加载 {len(self._users)} 个库街区绑定账号")

    async def _save_data(self):
        path = self._get_data_file()

        def _write():
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self._users, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"保存绑定数据失败: {e}")

        await asyncio.to_thread(_write)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _get_at_target(self, event: AstrMessageEvent) -> Optional[str]:
        bot_self = event.get_self_id()
        for comp in event.message_obj.message:
            if isinstance(comp, At) and str(comp.qq) != "all":
                qq = str(comp.qq)
                if bot_self and qq == str(bot_self):
                    continue
                return qq
        return None

    def _get_threshold(self, rec: dict) -> int:
        t = rec.get("threshold")
        if t is None:
            t = int(self.config.get("default_threshold", 230))
        return max(0, int(t))

    @staticmethod
    def _format_energy(player_id: str, energy: EnergyInfo) -> str:
        remain, max_ = energy.remain, energy.max
        if energy.total_second and energy.total_second > 0:
            minutes = max(1, (energy.total_second + 59) // 60)
            full_txt = f"回满还需约 {minutes} 分钟"
        else:
            full_txt = "体力已回满"
        now = datetime.now().strftime("%H:%M:%S")
        return (
            f"【鸣潮体力】玩家 {player_id}\n"
            f"当前体力：{remain}/{max_}\n"
            f"{full_txt}\n"
            f"查询时间：{now}"
        )

    async def _do_query(self, rec: dict) -> str:
        """查询体力并返回格式化文本。"""
        try:
            energy = await self.client.query_energy(rec)
        except KuroAuthError:
            return "Token 已失效，请重新获取 Token 后发送 /体力绑定 <用户ID> <Token>"
        except KuroAPIError as e:
            return f"查询体力失败：{e}"
        return self._format_energy(rec.get("playerId", "?"), energy)

    # ------------------------------------------------------------------
    # 指令（全部独立命令，不使用 command_group）
    # ------------------------------------------------------------------
    @filter.command("体力查询")
    async def cmd_query(self, event: AstrMessageEvent):
        """查询自己的体力（未绑定会提示绑定）"""
        # 管理员 @ 查他人
        target_qq = self._get_at_target(event)
        if target_qq and str(target_qq) != str(event.get_sender_id()):
            if not event.is_admin():
                yield event.plain_result("你没有权限查询其他用户的体力哦~")
                return
            rec = self._users.get(str(target_qq))
            if not rec:
                yield event.plain_result(f"用户 {target_qq} 尚未绑定库街区账号")
                return
            yield event.plain_result(await self._do_query(rec))
            return

        # 查询自己
        rec = self._users.get(str(event.get_sender_id()))
        if not rec:
            yield event.plain_result(
                "你还没有绑定库街区账号。\n"
                "请发送：/体力绑定 <用户ID> <Token>\n"
                "（Token 获取方法见插件 README）"
            )
            return
        yield event.plain_result(await self._do_query(rec))

    @filter.command("体力绑定")
    async def cmd_bind(self, event: AstrMessageEvent, uid: str, token: str):
        """绑定库街区 Token：/体力绑定 <用户ID> <Token>"""
        qq = str(event.get_sender_id())
        uid = uid.strip()
        token = token.strip()

        try:
            user_info = await self.client.get_user_info(uid, token)
        except KuroAuthError as e:
            yield event.plain_result(
                f"Token 无效或已失效：{e}\n"
                "请重新获取 Token 后再次绑定（获取方法见插件 README）"
            )
            return
        except KuroAPIError as e:
            yield event.plain_result(
                f"校验 Token 失败：{e}\n"
                "请确认 Token 和用户 ID 正确（获取方法见插件 README）"
            )
            return

        try:
            player = await self.client.get_player_info(token, uid)
        except KuroAuthError as e:
            yield event.plain_result(
                f"Token 无效或已失效：{e}\n"
                "请重新获取 Token 后再次绑定"
            )
            return
        except KuroAPIError as e:
            yield event.plain_result(f"获取玩家信息失败：{e}")
            return

        record = {
            "qq": qq,
            "nickname": event.get_sender_name() or user_info.user_name,
            "token": token,
            "uid": uid,
            "playerId": str(player.player_id),
            "serverId": str(player.server_id),
            "roleId": str(player.role_id),
            "group_id": event.get_group_id(),
            "umo": event.unified_msg_origin,
            "platform": event.get_platform_name(),
            "threshold": None,
            "last_remind_ts": 0,
        }
        self._users[qq] = record
        await self._save_data()

        try:
            energy = await self.client.query_energy(record)
        except KuroAPIError as e:
            yield event.plain_result(
                f"绑定成功，但查询体力失败：{e}\n"
                "可稍后发送 /体力查询 手动查询"
            )
            return
        yield event.plain_result(
            f"绑定成功！玩家ID：{player.player_id}\n"
            + self._format_energy(player.player_id, energy)
        )

    @filter.command("体力提醒")
    async def cmd_remind(self, event: AstrMessageEvent, threshold: int = -1):
        """设置体力提醒阈值：/体力提醒 <阈值>（0 关闭；不带参数查看当前设置）"""
        qq = str(event.get_sender_id())
        rec = self._users.get(qq)
        if not rec:
            yield event.plain_result("请先绑定：/体力绑定 <用户ID> <Token>")
            return

        if threshold < 0:
            cur = self._get_threshold(rec)
            yield event.plain_result(
                f"当前提醒阈值：{cur if cur > 0 else '（已关闭）'}\n"
                f"修改请发送：/体力提醒 <数值>；关闭请发送：/体力提醒 0"
            )
            return

        rec["threshold"] = threshold
        rec["last_remind_ts"] = 0
        await self._save_data()
        if threshold <= 0:
            yield event.plain_result("已关闭体力提醒。")
        else:
            yield event.plain_result(
            f"已设置：当体力达到或超过 {threshold} 时会在本群 @ 提醒你（快去清体力）。"
            )

    @filter.command("体力解绑")
    async def cmd_unbind(self, event: AstrMessageEvent):
        """解绑当前账号：/体力解绑"""
        qq = str(event.get_sender_id())
        if qq in self._users:
            del self._users[qq]
            await self._save_data()
            yield event.plain_result("已解绑，不再查询与提醒你的体力。")
        else:
            yield event.plain_result("你还没有绑定库街区账号。")

    @filter.command("体力列表")
    async def cmd_list(self, event: AstrMessageEvent):
        """查看已绑定账号列表（仅管理员）：/体力列表"""
        if not event.is_admin():
            yield event.plain_result("仅管理员可查看绑定列表。")
            return
        if not self._users:
            yield event.plain_result("当前没有任何绑定账号。")
            return
        lines = ["【已绑定账号】"]
        for qq, rec in self._users.items():
            lines.append(
                f"- {rec.get('nickname', qq)} ({qq})：玩家 {rec.get('playerId', '?')}，"
                f"阈值 {self._get_threshold(rec) if self._get_threshold(rec) > 0 else '关'}"
            )
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------
    # 整点自动刷新任务
    # ------------------------------------------------------------------
    async def _hourly_refresh_loop(self):
        """每个整点自动刷新所有绑定用户的体力数据。"""
        while True:
            try:
                now = datetime.now()
                next_hour = now.replace(minute=0, second=0, microsecond=0)
                seconds_until = max(1, int(next_hour.timestamp() + 3600 - now.timestamp()))
                await asyncio.sleep(seconds_until)

                if not self._users:
                    continue
                logger.info("【鸣潮体力】整点自动刷新开始")
                refreshed = 0
                for qq, rec in list(self._users.items()):
                    try:
                        await self.client.query_energy(rec)
                        refreshed += 1
                    except KuroAuthError:
                        logger.warning(f"【鸣潮体力】用户 {qq} 的 Token 已失效，跳过刷新")
                    except KuroAPIError as e:
                        logger.warning(f"【鸣潮体力】刷新用户 {qq} 体力失败: {e}")
                logger.info(f"【鸣潮体力】整点刷新完成，成功 {refreshed}/{len(self._users)}")
            except asyncio.CancelledError:
                logger.info("鸣潮体力整点刷新任务已停止")
                return
            except Exception as e:
                logger.error(f"鸣潮体力整点刷新任务异常: {e}")

    # ------------------------------------------------------------------
    # 提醒定时任务
    # ------------------------------------------------------------------
    async def _reminder_loop(self):
        while True:
            try:
                interval = max(1, int(self.config.get("check_interval_minutes", 10))) * 60
                await asyncio.sleep(interval)
                if not self.config.get("enable_reminder", True):
                    continue
                await self._check_reminders()
            except asyncio.CancelledError:
                logger.info("鸣潮体力提醒任务已停止")
                return
            except Exception as e:
                logger.error(f"鸣潮体力提醒任务异常: {e}")

    async def _check_reminders(self):
        now = time.time()
        cooldown = max(0, int(self.config.get("remind_cooldown_minutes", 120))) * 60
        for qq, rec in list(self._users.items()):
            try:
                threshold = self._get_threshold(rec)
                if threshold <= 0:
                    continue
                umo = rec.get("umo")
                if not umo:
                    continue
                if now - rec.get("last_remind_ts", 0) < cooldown:
                    continue

                energy = await self.client.query_energy(rec)
                if energy.remain < threshold:
                    continue

                remain, max_ = energy.remain, energy.max
                if energy.total_second and energy.total_second > 0:
                    minutes = max(1, (energy.total_second + 59) // 60)
                else:
                    minutes = 0
                template = str(
                    self.config.get(
                        "remind_message_template",
                        "【鸣潮体力提醒】当前体力 {remain}/{max}，体力快满了，记得去清体力哦~",
                    )
                )
                text = (
                    template.replace("{remain}", str(remain))
                    .replace("{max}", str(max_))
                    .replace("{minutes}", str(minutes))
                    .replace("{playerId}", str(rec.get("playerId", "")))
                )
                chain = (
                    MessageChain()
                    .at(rec.get("nickname") or "", qq)
                    .message("\u200b" + text)
                )
                ok = await self.context.send_message(umo, chain)
                if ok:
                    rec["last_remind_ts"] = now
                    await self._save_data()
                    logger.info(f"已提醒用户 {qq}：体力 {remain}/{max_} 已达到阈值 {threshold}")
            except KuroAuthError:
                logger.warning(f"用户 {qq} 的 Token 已失效，跳过提醒；请其重新绑定")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"检查用户 {qq} 体力失败: {e}")
