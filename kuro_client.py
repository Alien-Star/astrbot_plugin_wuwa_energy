"""库街区 (Kuro BBS) API 客户端 —— PC 网页版 (H5) 实现。

接口参考 https://github.com/TomyJan/Kuro-API-Collection
请求头参考 https://github.com/lango578/astrbot_plugin_kuro_checkin
身份认证：用户在网页版 https://www.kurobbs.com 登录后，从 Cookie 中获取 user_token。
"""
from dataclasses import dataclass
from typing import Optional

import aiohttp

GAME_ID_WUWA = "3"  # 鸣潮（网页版接口 gameId=3）

# PC 网页版 (H5) 固定设备标识
_DEV_CODE = "QZlE9fzPUlHON9FGUsfLfWwyM2dRKr6K"
_DISTINCT_ID = "19dafdce461609-023472cbe40c9b-1e462c69-2073600-19dafdce462ebd"

_PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class KuroAPIError(Exception):
    """库街区 API 调用失败。"""


class KuroAuthError(KuroAPIError):
    """Token 无效或已失效，需要重新获取 Token 后重新绑定。"""


@dataclass
class UserInfo:
    uid: str
    user_name: str = ""


@dataclass
class PlayerInfo:
    player_id: str
    server_id: str
    role_id: str
    game_id: str = GAME_ID_WUWA


@dataclass
class EnergyInfo:
    remain: int = 0
    max: int = 0
    second: int = 0  # 每恢复 1 点所需秒数
    total_second: int = 0  # 回满还需秒数
    update_time: str = ""


def _h5_headers(token: str) -> dict:
    """构造与 PC 网页版库街区完全一致的 H5 请求头。"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Host": "api.kurobbs.com",
        "Origin": "https://www.kurobbs.com",
        "Referer": "https://www.kurobbs.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": _PC_UA,
        "source": "h5",
        "version": "3.0.1",
        "devCode": _DEV_CODE,
        "distinct_id": _DISTINCT_ID,
        "token": token,
    }


class KuroBBSClient:
    def __init__(
        self,
        api_base: str = "https://api.kurobbs.com",
        timeout: int = 30,
        **_kwargs,  # 兼容旧配置项（request_style / dev_code 等，现已忽略）
    ):
        self.api_base = api_base.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _post(self, path: str, data: Optional[dict] = None, token: str = "") -> dict:
        """统一 POST 请求（网页版全部用 POST + form-encoded）。"""
        session = await self._get_session()
        headers = _h5_headers(token)
        url = self.api_base + path
        try:
            async with session.post(url, data=data or {}, headers=headers) as resp:
                try:
                    payload = await resp.json(content_type=None)
                except Exception:
                    raise KuroAPIError(f"HTTP {resp.status}: 响应不是合法 JSON")
        except aiohttp.ClientError as e:
            raise KuroAPIError(f"网络请求失败: {e}")

        code = payload.get("code")
        if code != 200:
            msg = payload.get("msg") or payload.get("message") or str(payload)
            lowered = str(msg).lower()
            if code in (401, 403, 1003, 220) or any(
                k in lowered
                for k in ("token", "未登录", "登录已失效", "登录失效", "凭证", "请先登录", "过期")
            ):
                raise KuroAuthError(f"code={code} msg={msg}")
            raise KuroAPIError(f"code={code} msg={msg}")
        data_resp = payload.get("data")
        if isinstance(data_resp, (dict, list)):
            return data_resp
        return {}

    # ------------------------------------------------------------------
    # 用户信息（校验 Token）
    # ------------------------------------------------------------------
    async def get_user_info(self, uid: str, token: str) -> UserInfo:
        """校验 Token 并获取用户信息。

        POST /user/mineV2   body: size=10
        """
        resp = await self._post("/user/mineV2", {"size": "10"}, token)
        mine = resp.get("mine") or {}
        return UserInfo(
            uid=str(mine.get("userId") or uid),
            user_name=str(mine.get("userName") or ""),
        )

    # ------------------------------------------------------------------
    # 玩家信息
    # ------------------------------------------------------------------
    async def get_player_info(self, token: str, uid: str) -> PlayerInfo:
        """获取鸣潮玩家角色信息（playerId/serverId/roleId）。

        POST /gamer/role/list   body: gameId=3
        备用：POST /user/role/findRoleList   body: gameId=3
        """
        for endpoint in ("/gamer/role/list", "/user/role/findRoleList"):
            resp = await self._post(endpoint, {"gameId": GAME_ID_WUWA}, token)
            # data 可能直接是列表，也可能是字典含 roleList
            if isinstance(resp, list):
                role_list = resp
            elif isinstance(resp, dict):
                role_list = resp.get("roleList", [])
            else:
                role_list = []
            if isinstance(role_list, list) and role_list:
                r = role_list[0]
                if isinstance(r, dict):
                    player_id = str(r.get("playerId") or r.get("userId") or "")
                    server_id = str(r.get("serverId") or "")
                    role_id = str(r.get("roleId") or "")
                    if player_id and server_id and role_id:
                        return PlayerInfo(
                            player_id=player_id,
                            server_id=server_id,
                            role_id=role_id,
                            game_id=GAME_ID_WUWA,
                        )
        raise KuroAPIError("获取玩家信息失败：未找到鸣潮角色")

    # ------------------------------------------------------------------
    # 体力查询（使用 refresh 端点获取实时数据）
    # ------------------------------------------------------------------
    async def query_energy(self, record: dict) -> EnergyInfo:
        """查询体力（结晶波片）—— 实时刷新。

        先调 POST /gamer/widget/game3/refresh 强制刷新数据，
        再从响应中读取 energyData。
        body: gameId=3&roleId=<roleId>&serverId=<serverId>&sizeType=1&type=2
        响应 data.energyData 含 cur(当前) / total(上限) / refreshTimeStamp(回满时间戳)。
        """
        token = record.get("token") or ""
        if not token:
            raise KuroAPIError("绑定数据缺少 token，请重新绑定")
        data = {
            "gameId": str(record.get("gameId", GAME_ID_WUWA)),
            "roleId": str(record.get("roleId", "")),
            "serverId": str(record.get("serverId", "")),
            "sizeType": "1",
            "type": "2",
        }
        # refresh 端点返回更准确的数据
        resp = await self._post("/gamer/widget/game3/refresh", data, token)
        energy_data = resp.get("energyData") or {}
        cur = int(energy_data.get("cur", 0) or 0)
        total = int(energy_data.get("total", 0) or 0)
        refresh_ts = energy_data.get("refreshTimeStamp") or 0
        server_time = int(resp.get("serverTime", 0) or 0)
        # 回满还需秒数
        total_second = 0
        if refresh_ts and server_time and refresh_ts > server_time:
            total_second = refresh_ts - server_time
        return EnergyInfo(
            remain=cur,
            max=total,
            second=0,
            total_second=total_second,
            update_time="",
        )
