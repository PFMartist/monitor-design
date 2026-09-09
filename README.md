# Device Monitor

一个面向 Windows 小主机、NAS 和家庭服务器的轻量监控面板。每台设备运行一个 Python Agent，浏览器直接轮询各 Agent；不需要数据库、中心服务或前端构建工具。

## 功能

- CPU、内存、磁盘、网络、运行时间、温度和 GPU 指标
- TCP 端口、MAA / MaaEnd 日志、AdGuard Home、Syncthing、µTorrent 和 WebDAV 检查
- 单文件 HTML 仪表盘，支持暗色与 CRT 主题、拖拽排序和轮询间隔设置
- 通过仪表盘读取和更新 Agent 的 `config.json`
- Windows 任务计划程序自启动和副屏全屏启动脚本
- 可选的本地聊天终端，使用 Anthropic 兼容 API；密钥不写入前端

## 架构

```text
Windows device A ─ agent.py:9090 ─┐
Windows device B ─ agent.py:9090 ─┼─ browser / dashboard.html
Local machine   ─ agent.py:9090 ──┘
```

## 快速开始

需要 Python 3.10+。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item deploy\config-local.example.json config.json
python agent.py --port 9090
```

另开终端验证：

```powershell
Invoke-RestMethod http://localhost:9090/
```

然后直接打开 `dashboard.html`，在设置面板中填写各设备的 Agent URL。页面设置保存在浏览器 `localStorage`。

## 服务配置

将一个示例文件复制为 Agent 同目录下的 `config.json`：

- `deploy/config-local.example.json`
- `deploy/config-server.example.json`
- `deploy/config-nas.example.json`

支持的类型：

| 类型 | 主要参数 | 用途 |
|---|---|---|
| `port` | `host`, `port` | TCP 端口探测 |
| `maa` | `process_name`, `log_dir`, `log_glob` | MAA 进程和日志 |
| `maaend` | `process_name`, `log_dir`, `log_glob` | MaaEnd 进程和日志 |
| `adguard` | `api_url` | AdGuard Home API |
| `syncthing` | `api_url` | Syncthing API |
| `utorrent` | `api_url` | µTorrent WebUI |
| `webdav` | `url` | HTTP HEAD 探测 |

凭据仅通过环境变量传入：

```powershell
$env:ADGUARD_USER = "admin"
$env:ADGUARD_PASS = "your-password"
$env:SYNCTHING_KEY = "your-api-key"
$env:UTORRENT_USER = "admin"
$env:UTORRENT_PASS = "your-password"
```

## Windows 部署

把 `agent.py`、`slow_metrics.ps1`、`config.json` 和 `deploy` 中的安装脚本放在同一目录。以管理员身份运行 `deploy/install_task.bat` 可创建登录自启任务。

仪表盘可用 `deploy/dashboard.bat` 启动；`deploy/install_dashboard.bat` 可设置登录后自动在副屏打开。

## 可选聊天终端

```powershell
pip install -r requirements-chat.txt
```

在 `%APPDATA%\monitor_chat\config.json` 中配置：

```json
{
  "base_url": "https://api.anthropic.com",
  "api_key": "your-api-key",
  "model": "claude-sonnet-4-5"
}
```

也可以通过 `MONITOR_CHAT_API_KEY` 设置密钥。聊天后端只监听 `127.0.0.1`，由本机 Agent 在仪表盘展开终端时按需启动。

## 安全提示

Agent 当前没有身份认证，并监听 `0.0.0.0:9090`。请只在可信局域网或 VPN/组网环境中使用，通过 Windows 防火墙限制来源；不要直接暴露到互联网。公开部署前建议增加认证和 HTTPS 反向代理。

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

## 资源说明

`assets/` 中的角色图像不自动随代码许可证授权。公开发布前请确认你拥有这些图像的再分发权，并单独声明其来源与许可。
