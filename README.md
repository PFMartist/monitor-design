# Device Monitor

Device Monitor 是一个面向 Windows 小主机、NAS 和家庭服务器的轻量级监控面板。每台设备运行独立的 Python Agent，浏览器直接轮询各 Agent，无需数据库、中心服务或前端构建工具。

## 功能

- CPU、内存、磁盘、网络、运行时间、温度和 GPU 指标
- TCP 端口、MAA / MaaEnd 日志、AdGuard Home、Syncthing、µTorrent 和 WebDAV 状态检查
- 单文件 HTML 仪表盘，支持暗色与 CRT 主题、拖拽排序和轮询间隔设置
- 通过仪表盘读取和更新 Agent 的 `config.json`
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

Agent 当前不提供身份认证，并默认监听 `0.0.0.0:9090`。它只适合在可信局域网、VPN 或其他受控网络中运行，不应直接暴露到互联网。跨越可信网络边界部署时，需要通过防火墙限制来源，并增加身份认证和 HTTPS 反向代理。

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
