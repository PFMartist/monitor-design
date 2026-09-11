# Device Monitor

Device Monitor 是一个面向 Windows 小主机、NAS 和家庭服务器的轻量级监控面板。每台设备运行独立的 Python Agent，浏览器直接轮询各 Agent，无需数据库、中心服务或前端构建工具。

## 功能

- CPU、内存、磁盘、网络、运行时间、温度和 GPU 指标
- TCP 端口、MAA / MaaEnd 日志、AdGuard Home、Syncthing、µTorrent 和 WebDAV 状态检查
- 单文件 HTML 仪表盘，支持暗色与 CRT 主题、拖拽排序和轮询间隔设置
- 通过仪表盘读取和更新 Agent 的 `config.json`
- 来源地址白名单：只处理指定网段的请求，默认仅本机回环；POST 强制 JSON
- Windows 任务计划程序自启动和副屏全屏启动脚本
- 可选本地聊天终端，支持 Anthropic 兼容 API；API 密钥不会写入前端

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

凭据通过环境变量传入，不应写入 `config.json`：

```powershell
$env:ADGUARD_USER = "admin"
$env:ADGUARD_PASS = "your-password"
$env:SYNCTHING_KEY = "your-api-key"
$env:UTORRENT_USER = "admin"
$env:UTORRENT_PASS = "your-password"
```

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
  "model": "claude-sonnet-4-5"
}
```

API 密钥也可通过 `MONITOR_CHAT_API_KEY` 环境变量设置。聊天后端仅监听 `127.0.0.1`，并由本机 Agent 在仪表盘展开终端时按需启动。

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

## 项目结构

```text
agent.py                 # 指标与服务检查 Agent
dashboard.html           # 单文件仪表盘
slow_metrics.ps1         # Windows 温度和 GPU 采集
assets/                  # CRT 主题资源
deploy/                  # 示例配置、启动和安装脚本
requirements.txt
requirements-chat.txt
```

## 资源与许可

`assets/` 中的角色图像由生成式 AI 制作。仓库目前未附带开源许可证，代码和资源默认保留所有权利。
