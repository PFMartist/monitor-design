# Device Monitor

Device Monitor 是一个面向 Windows 小主机、NAS 和家庭服务器的轻量级监控面板。每台设备运行独立的 Python Agent，浏览器直接轮询各 Agent，无需数据库、中心服务或前端构建工具。

## 功能

- CPU、内存、磁盘、网络、运行时间、温度和 GPU 指标
- TCP 端口、MAA / MaaEnd 日志、AdGuard Home、Syncthing、µTorrent 和 WebDAV 状态检查
- DeepSeek 余额与 OpenCode Go 套餐额度查询（账户级，独立于任何一台设备显示）
- 单文件 HTML 仪表盘，内置 CRT 与终末地两套主题、拖拽排序和轮询间隔设置
- 通过仪表盘读取和更新 Agent 的 `config.json`
- 来源地址白名单：只处理指定网段的请求，默认仅本机回环；POST 强制 JSON
- Windows 任务计划程序自启动和副屏全屏启动脚本
- 可选本地聊天终端，支持 Anthropic 兼容 API；API 密钥不会写入前端
- 聊天终端按主题切换人格（CRT 是初音未来，终末地是终末地工业的官方发言人）

## 架构

```text
Windows device A ─ agent.py:9090 ─┐
Windows device B ─ agent.py:9090 ─┼─ browser / dashboard.html
Local machine   ─ agent.py:9090 ──┘
```

## 运行要求

- Windows
- Python 3.10+
- 可访问各 Agent 地址的浏览器

部分温度与 GPU 指标依赖 Windows 和本机硬件支持。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item deploy\config-local.example.json config.json
python agent.py --port 9090
```

Agent 健康检查：

```powershell
Invoke-RestMethod http://localhost:9090/
```

打开 `dashboard.html` 后，在设置面板中配置各设备的 Agent URL。仪表盘设置保存在浏览器 `localStorage` 中。

> Agent 默认只接受**本机回环**的请求。要轮询其他机器，需要在那台 Agent 上设置 `MONITOR_ALLOW_NETS`，详见[安全模型](#安全模型)。

## Agent 配置

Agent 从同目录下的 `config.json` 读取配置。仓库提供三份示例：

- `deploy/config-local.example.json`
- `deploy/config-server.example.json`
- `deploy/config-nas.example.json`

可用检查类型：

| 类型 | 主要参数 | 用途 |
|---|---|---|
| `port` | `host`, `port` | TCP 端口探测 |
| `maa` | `process_name`, `log_dir`, `log_glob` | MAA 进程和日志 |
| `maaend` | `process_name`, `log_dir`, `log_glob` | MaaEnd 进程和日志 |
| `adguard` | `api_url` | AdGuard Home API |
| `syncthing` | `api_url` | Syncthing API |
| `utorrent` | `api_url` | µTorrent WebUI |
| `webdav` | `url` | HTTP HEAD 探测 |
| `deepseek` | `low_balance`（可选） | DeepSeek 账户余额 |
| `opencode` | —— | OpenCode Go 套餐额度（5 小时 / 周 / 月） |

`deepseek` 和 `opencode` 是**账户级**检查，不属于任何一台设备 —— 它们在仪表盘底部单独一行显示，不占用设备卡片。放在哪台 Agent 上由你决定，通常是常开的那台。

凭据通过环境变量传入，不应写入 `config.json`：

```powershell
$env:ADGUARD_USER = "admin"
$env:ADGUARD_PASS = "your-password"
$env:SYNCTHING_KEY = "your-api-key"
$env:UTORRENT_USER = "admin"
$env:UTORRENT_PASS = "your-password"
$env:DEEPSEEK_API_KEY = "your-key"
$env:OPENCODE_API_KEY = "your-key"
```

Agent **只从这些环境变量读取凭据**，不读取任何其它程序的配置文件，也不从命令行参数取（同用户下的其它进程能读到进程列表）。密钥只会以环境变量或 `config.json` 的形式出现在这台机器上，且永不下发给浏览器。

## 余额与额度检查

两个账户级检查直接向厂商 API 取数，因此和本地检查有几处不同：

| | `deepseek` | `opencode` |
|---|---|---|
| 端点 | `GET https://api.deepseek.com/user/balance`（有公开文档） | `GET https://opencode.ai/zen/go/v1/usage`（未公开，只有这一个路径可用） |
| 返回 | 账户余额 | 三个额度窗口的已用百分比（5 小时 / 周 / 月） |
| 取数 | `urllib` | `curl.exe`（见下） |
| 密钥 | `DEEPSEEK_API_KEY` | `OPENCODE_API_KEY` |

设计取舍：

- **目标主机写死在代码里**，不像其它检查那样可以配 `api_url`。Agent 没有身份认证，而 `POST /config` 只要能连上端口就能打 —— 如果 URL 可配，任何能碰到端口的人都能把它指向自己的服务器，坐在那儿收 `Authorization` 头里的密钥。要加镜像或代理只能改代码。
- **结果缓存 5 分钟**（失败 30 秒）。仪表盘每几秒轮询一次，余额不会变动那么快；不缓存的话，一个失效的密钥会让每次轮询都变成一次外网请求。
- **缓存身份包含密钥指纹**，换密钥后不会继续显示上一个账户的数字。
- **传输失败与鉴权失败区别对待**：网络超时保留上一次的读数并标记为陈旧，鉴权失败（401/403）立即作废 —— 那些数字描述的是一个你已经用不了的账户。
- **密钥不会回传到浏览器**：接口只返回数字和一两个稳定的错误码，没配密钥时显示 `offline · no key`。

### opencode 为什么走 curl

`opencode.ai` 在 Cloudflare 后面，会按 TLS 指纹判断客户端：Python 的 `urllib` 直接吃到 `403 Error 1010`（browser_signature_banned），请求还没走到鉴权就被挡了；同一个密钥换 `curl.exe` 就正常返回。

所以这个检查用 `curl.exe` 子进程取数，密钥通过 `-K -` 从 **stdin** 传给 curl（不放在命令行参数里 —— 同一用户下的其它进程能读到进程列表）。这是 Agent 里的第三个子进程，前两个是 `slow_metrics.ps1` 和 `nvidia-smi`，都带 `CREATE_NO_WINDOW` 以免弹窗。

### Windows 上的一个 urllib 陷阱

`urllib` 每次请求都会读系统代理设置，而 CPython 的绕过判定里有一句 `socket.getfqdn()` —— 一次**反向 DNS 查询**，发生在请求发出之前。回环地址有 hosts 记录、瞬间返回；其余地址要等满解析超时。实测同一请求：

| 目标 | 默认 opener | 换用空 `ProxyHandler` |
|---|---|---|
| `127.0.0.1` | 0 ms | 0 ms |
| 局域网地址 | ~6000 ms | 19 ms |
| 外部 HTTPS | ~4600 ms | 121 ms |

值得注意的是触发条件：**只有系统里配了代理，Python 才会去做这个绕过判定** —— 于是"绕过"这个动作本身成了开销，跟代理转发与否无关。所以 Agent 里所有检查的 HTTP 调用都走一个 `_NO_PROXY_OPENER`（`build_opener(ProxyHandler({}))`）：这些检查要么打回环、要么直连外网，本来就不需要系统代理。`deploy/diag_poll.py` 同样处理过 —— 它以前会把这份开销算进网络延迟里。

## Windows 部署

部署目录需要包含 `agent.py`、`slow_metrics.ps1`、`config.json` 和 `deploy` 中的安装脚本。

- `deploy/install_task.bat`：以管理员身份创建 Agent 登录自启动任务
- `deploy/dashboard.bat`：启动仪表盘
- `deploy/install_dashboard.bat`：设置仪表盘登录后在副屏启动

## 可选聊天终端

安装额外依赖：

```powershell
pip install -r requirements-chat.txt
```

配置文件位置为 `%APPDATA%\monitor_chat\config.json`：

```json
{
  "base_url": "https://api.anthropic.com",
  "api_key": "your-api-key",
  "model": "claude-sonnet-4-5",
  "prompts": {}
}
```

`base_url` / `model` 也可通过 `MONITOR_CHAT_BASE_URL`、`MONITOR_CHAT_MODEL` 环境变量设置，API 密钥用 `MONITOR_CHAT_API_KEY`。聊天后端仅监听 `127.0.0.1`，并由本机 Agent 在仪表盘展开终端时按需启动。

### 按主题切换人格

仪表盘每次发消息都会带上当前主题，后端据此选择 system prompt，并**按主题分别保存历史** —— 换主题开始一段新对话，而不是把上一个人格的聊天记录塞给新的那个人格。库里内置两套：

| 主题 | 人格 |
|---|---|
| `crt` | 初音未来 |
| `endfield` | 终末地工业的官方发言人 |

主题名不认识、或请求里根本没带，都落到 `crt` 那套（那只是后端的兜底；仪表盘自己的默认主题是终末地）。要换成自己的 prompt，不必改代码，在配置里加一个 `prompts` 对象即可（键是主题名）：

```json
{
  "prompts": { "endfield": "你是……", "default": "……" }
}
```

## 安全模型

Agent 不提供身份认证，因此它自己限制来源：只有源地址落在允许网段内的请求才会被处理，其余在进入任何 API 逻辑之前直接返回 403。

出于安全默认，允许网段**只有本机回环**。要让别的机器上的仪表盘访问某台 Agent，需要在那台 Agent 上显式声明仪表盘流量的来源网段：

```powershell
$env:MONITOR_ALLOW_NETS = "10.0.0.0/24,127.0.0.1/32"
```

逗号分隔的 CIDR，可写在 `deploy/run_agent.bat` 里随启动生效；留空表示拒绝所有来源。判断依据是 **TCP 对端地址**，不读取 `X-Forwarded-For` / `X-Real-IP` 这类客户端可以随意伪造的请求头。

另外，所有 POST 必须带 `Content-Type: application/json`，否则返回 415。这顺带让跨域 POST 成为非简单请求，浏览器会先发 preflight 而不是直接盲发。

需要注意这不是身份认证：**任何能从允许网段发包的主机都被视为可信**。所以网段要尽量收窄，并且 Agent 仍只适合在可信局域网、VPN 或其他受控网络中运行，不应直接暴露到互联网。跨越可信网络边界部署时，建议叠加防火墙限制、身份认证和 HTTPS 反向代理。

撞到 403 时：Agent 启动会打印生效的名单，被拒绝的请求也会打印一行。注意 `pythonw` 下没有 stdout，需要前台运行才看得到：

```powershell
python agent.py --port 9090
# [monitor] accepting only source IPs in: 127.0.0.1/32, ::1/128
# [monitor] refused GET / from 10.0.0.9
```

更多信息见 [SECURITY.md](SECURITY.md)。

## 主题与资源

仪表盘是单个 HTML 文件，两套主题都在里面，默认是终末地：

- **CRT** —— 终端配色，配 `assets/miku*/` 里的初音未来帧动画（三套配色，界面上可切换）。
- **终末地** —— 浅色工业风，卡片底纹共用一张 `assets/ef-contour.jpg` 等高线图（靠 `background-attachment: fixed` 让所有卡片取到同一张背景的不同区域，而不是每张卡片各贴一份）。旗帜徽标是内联 SVG，不额外请求文件。

`refs/` 放的是主题素材的来源与再生方法，不是运行时代码：官方素材怎么取的、配色怎么定的、卡片高度和聊天展开是怎么量出来的，连同全部再生脚本。仪表盘里指向它的注释也是这个意思 —— 想改主题外观时先看那里。[`refs/README.md`](refs/README.md) 是入口。

`archive/` 是两份旧版本快照（五主题时代、以及更早的 Dark/CRT/Light 时代）。`refs/` 下的脚本是**幂等改写**而不是生成器 —— 它们只改指定声明，没法从零重建仪表盘，所以改之前留快照。

## 项目结构

```text
agent.py                 # 指标与服务检查 Agent
dashboard.html           # 单文件仪表盘（CRT + 终末地两套主题）
slow_metrics.ps1         # Windows 温度和 GPU 采集
assets/                  # 主题资源：miku*/ 帧动画、ef-* 终末地素材
refs/                    # 主题素材来源、配色与再生脚本
archive/                 # 仪表盘旧版本快照
deploy/                  # 示例配置、启动和安装脚本
requirements.txt
requirements-chat.txt
SECURITY.md              # 威胁模型与暴露面
THIRD-PARTY-NOTICES.md   # 第三方素材的来源与许可
```

## 资源与许可

`assets/miku*/` 中的角色图像由生成式 AI 制作，角色归 Crypton Future Media 所有；`assets/ef-*` 与 `refs/` 下的徽标、底纹来自《明日方舟：终末地》官方素材（及其描摹），商标归鹰角网络 / Studio Montagne 所有，此处仅用于个人、非官方的界面；`refs/perlica-skill.md` 是 MaaEnd 项目的文件，按 **AGPL-3.0** 授权，那份许可（而不是本仓库的）管辖它。

**逐项来源与许可见 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。**

本仓库自己的代码与文档目前未附带开源许可证，默认保留所有权利 —— 这一句不覆盖上面那些第三方材料。
