# astrbot_plugin_wuwa_energy · 鸣潮体力助手

基于库街区 (Kuro BBS) API 的 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件：
查询鸣潮 (Wuthering Waves) 体力（结晶波片），并在体力低于设定阈值时在群内 **@ 提醒**。

接口参考 [TomyJan/Kuro-API-Collection](https://github.com/TomyJan/Kuro-API-Collection)。
身份认证使用**网页版库街区 Token**（库街区已不支持密码登录，只能短信验证码登录网页版后提取 Token）。

> ⚠️ **重要提醒**
>
> 1. **Token 时效性很短**，可能几小时到几天就失效，失效后需要重新获取并重新绑定，因此本插件实用性可能不高。插件会在 Token 失效时提示你。
> 2. **请只在自己的 AI 上使用本插件**，不要将 Token 发送到公共群聊中。Token 等同于你的登录凭证，泄露后他人可操作你的账号。
> 3. **因 Token 泄露导致的任何问题，本人概不负责。**

## 功能

| 指令 | 说明 |
| --- | --- |
| `/体力查询` | 查询自己的体力（当前值/上限/回满时间），每次查询自动刷新实时数据 |
| `/体力查询 @用户` | AstrBot 管理员可查询指定用户的体力 |
| `/体力绑定 <用户ID> <Token>` | 绑定库街区账号（Token 获取方法见下文） |
| `/体力提醒 <阈值>` | 设置提醒阈值；`0` 关闭；不带参数查看当前设置 |
| `/体力解绑` | 解绑自己的账号 |
| `/体力列表` | （AstrBot 管理员）查看已绑定账号 |

体力低于阈值时，后台定时任务会在绑定所在的群 **@ 你** 并发送提醒文案。
同一用户两次提醒之间至少间隔 `remind_cooldown_minutes`（默认 120 分钟），避免刷屏。

**自动刷新**：插件内置两个后台定时任务——
- **整点自动刷新**：每个整点自动刷新所有绑定用户的体力数据，保持数据新鲜
- **提醒检查**：每隔 `check_interval_minutes` 分钟检查一次，体力低于阈值则 @ 提醒

## 获取 Token（网页版库街区）

1. 浏览器打开 **https://www.kurobbs.com** 并登录（短信验证码登录）。
2. 按 `F12` 打开开发者工具，切换到 **Network（网络）** 面板，刷新页面。
3. 在请求列表中点击任意一个发往 **`api.kurobbs.com`** 的请求，在右侧 **Headers（请求头）** 中找到：
   - **`token`**：一长串字符，就是 Token；
   - **`uid`**：一串数字，就是用户 ID。
4. 将这两个值分别复制，发送：`/体力绑定 <uid> <token>`。

> 备用方法（Local Storage）：开发者工具 → **Application（应用）** → **Local Storage** → `https://www.kurobbs.com`，
> 找到键名 `userId` 与 `token` 对应的值，复制使用。

## 安装

1. 将本插件目录放入 AstrBot 的 `data/plugins/` 下（目录名 `astrbot_plugin_wuwa_energy`）。
2. 在 AstrBot WebUI「插件管理」中启用插件，并安装依赖：`pip install -r requirements.txt`（或由 AstrBot 自动安装）。
3. 在插件配置中按需调整：
   - `check_interval_minutes`：提醒检查间隔（默认 10 分钟）
   - `remind_cooldown_minutes`：同一用户两次提醒最小间隔（默认 120 分钟）
   - `default_threshold`：默认提醒阈值（默认 60）
   - `remind_message_template`：提醒文案模板（支持 `{remain}` `{max}` `{minutes}` `{playerId}` 变量）
4. 群内发送 `/体力绑定 <用户ID> <Token>` 完成绑定，再 `/体力提醒 <阈值>` 开启提醒。

## 接口说明

全部接口使用 **PC 网页版 (H5) 请求头**（`source: h5`、`version: 3.0.1`、PC 浏览器 UA、固定 `devCode`）。

| 用途 | 接口 | 说明 |
| --- | --- | --- |
| 用户信息/校验 Token | `POST /user/mineV2` | body: `size=10`；响应 `data.mine.userId` |
| 玩家角色信息 | `POST /gamer/role/list` | body: `gameId=3`；响应 `data[]` 含 `roleId`/`serverId`/`playerId` |
| 体力查询 | `POST /gamer/widget/game3/refresh` | body: `gameId=3&roleId=…&serverId=…&sizeType=1&type=2`；响应 `data.energyData.cur`/`.total`/`.refreshTimeStamp` |

> ⚠️ 体力查询使用 `refresh` 端点（而非 `getData`），因为 `getData` 返回的是缓存数据，
> `refresh` 会强制刷新返回实时数据。鸣潮 `gameId=3`。

## 说明与注意

- **Token 明文保存在本地** `data/plugin_data/astrbot_plugin_wuwa_energy/users.json`，仅用于调用库街区 API，不会上传到任何第三方。
- **Token 时效性很短**，失效后需按上述步骤重新获取并再次绑定（插件会在 Token 失效时给出提示）。
- 主动提醒依赖平台对主动消息的支持（aiocqhttp/OneBot 可用；QQ 官方 API 不支持主动消息）。
- 指令触发遵循 AstrBot 约定：需要以 `/` 开头或 @ 机器人。

## 免责声明

本插件仅供学习交流使用，与库街区/库洛游戏无关。

**请只在自己的 AI 上使用本插件，不要将 Token 发送到公共群聊中。**
**因 Token 泄露或使用本插件导致的任何问题，本人概不负责。**
