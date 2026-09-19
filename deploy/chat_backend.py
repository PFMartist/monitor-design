#!/usr/bin/env python3
"""Local chat backend for the Device Monitor Console (MIKU://CONSOLE).

Phase 2: plain JSON POST /api/chat (non-streaming reply).
API key lives only on this machine (config.json below or env var), never in
the browser. Bound to 127.0.0.1; CORS open for the file:// dashboard.

Model API: Anthropic or an Anthropic-compatible endpoint, reached with the
anthropic SDK and an explicit base_url.

Endpoints:
  GET  /api/ping   -> {"ok": true, "model": ..., "busy": ...}
  GET  /api/config -> {"model": ..., "base_url": ..., "api_key_set": bool}
  POST /api/chat   -> {"message": "...", "theme": "...", "reply": "..."}
                     | {"error": "..."}
                     (429 busy, 400 bad input, 502 upstream error)
  POST /api/config -> {"model": "..."} -> {"ok": true, "model": ...}
                     Model name ONLY. base_url and api_key are deliberately
                     not writable over HTTP — the key must never reach the
                     browser (see above); change those in config.json.

Config (first hit wins):
  %APPDATA%/monitor_chat/config.json: {"base_url": ..., "api_key": ...,
                                       "model": ..., "prompts": {...}}
  env MONITOR_CHAT_BASE_URL / MONITOR_CHAT_MODEL override the file defaults,
  env MONITOR_CHAT_API_KEY overrides the file key.

Phase 3 seam: switch to client.messages.stream(...) and forward SSE events.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import anthropic

DEFAULT_PORT = 12358
HISTORY_LIMIT = 30           # server-side conversation turns kept in memory
MAX_MESSAGE_CHARS = 2000
MAX_MODEL_CHARS = 200
MAX_TOKENS = 1024
REQUEST_TIMEOUT = 60

# Per-theme system prompts. The dashboard sends the active theme with each
# message; anything unrecognised — or a request that omits the field — falls
# back to `default`, which is also what an unmodified client gets.
#
# Any of these can be overridden without touching this file, by adding a
# "prompts" object to %APPDATA%\monitor_chat\config.json:
#
#   { "prompts": { "endfield": "你是……", "default": "……" } }
#
# History is kept per theme, so switching theme starts a fresh conversation
# rather than handing the new persona the previous one's transcript.
PROMPTS = {
    # CRT keeps the original persona.
    "default": (
        "你是初音未来（Hatsune Miku），苍绿色双马尾的虚拟歌手。"
        "性格安静，带一点忧郁，用中文轻声交流。"
    ),
    # Endfield speaks as Perlica. Condensed from MaaEnd's
    # `.agents/skills/perlica-style-reply/SKILL.md` (kept at
    # refs/perlica-skill.md); the full skill also carries rewrite drills and
    # worked examples that do not belong in a system prompt.
    "endfield": (
        "你是佩丽卡——《明日方舟：终末地》里终末地工业的监督与官方发言人，"
        "此刻值守在这套设施监测终端前，用户是你要照看的「管理员」。\n"
        "说话方式：冷静、利落、能拿主意，不拖泥带水。默认第一人称，"
        "不要用“如果我是佩丽卡”“佩丽卡会认为”这类旁述。先给判断或结论，"
        "再展开步骤；用词稳重、可执行（“我来处理”“先确认一下”“按这个方向推进”）。"
        "不堆感叹号，不频繁用语气词。可以在结尾补一句克制的安抚，"
        "例如“别担心，还在可控范围内，管理员”。偶尔可以轻描淡写带出一点私人侧面，"
        "但不要喧宾夺主。\n"
        "称呼：默认称对方为“管理员”，一般每段自然出现一次即可。\n"
        "边界：不写傲娇、疯癫、恋爱脑或尖刻毒舌；不高频卖萌、叠词、颜文字、"
        "网络梗；不为角色感牺牲事实准确性、操作步骤或风险提示。"
        "信息不确定时直说“我还不能直接下结论”“需要验证”“我先去确认”。"
        "用户要求退出角色时立刻退出。"
    ),
}


def config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "monitor_chat", "config.json")


def load_config() -> dict:
    cfg = {
        "base_url": os.environ.get("MONITOR_CHAT_BASE_URL", "https://api.anthropic.com"),
        "api_key": os.environ.get("MONITOR_CHAT_API_KEY", ""),
        "model": os.environ.get("MONITOR_CHAT_MODEL", "claude-sonnet-4-5"),
        "prompts": {},           # theme -> system prompt; overrides PROMPTS
    }
    try:
        with open(config_path(), encoding="utf-8") as f:
            file_cfg = json.load(f)
        for k in cfg:
            if file_cfg.get(k):
                cfg[k] = file_cfg[k]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    if os.environ.get("MONITOR_CHAT_API_KEY"):
        cfg["api_key"] = os.environ["MONITOR_CHAT_API_KEY"]
    return cfg


def save_config(cfg: dict) -> None:
    """Persist cfg, merging over whatever is already on disk.

    Only the keys present in cfg are written, so a UI-driven model change
    never drops base_url or api_key.
    """
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            on_disk = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        on_disk = {}
    on_disk.update({k: v for k, v in cfg.items() if v})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(on_disk, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class ChatError(Exception):
    pass


class ChatSession:
    busy = False

    def __init__(self, cfg: dict):
        self.cfg = cfg
        # theme -> deque([{"role","content"},...]). Kept separate so a persona
        # change does not inherit the previous one's transcript.
        self.histories: dict[str, deque] = {}
        self.lock = threading.Lock()
        self.client = anthropic.Anthropic(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            max_retries=1,
            timeout=REQUEST_TIMEOUT,
        )

    def _history(self, theme: str) -> deque:
        # Same normalisation as the HTTP edge, applied again here so any caller
        # of ask() lands on the same transcript rather than quietly opening a
        # new one for a stray key.
        theme = (theme or "").strip().lower()
        if theme not in PROMPTS:
            theme = "default"
        if theme not in self.histories:
            self.histories[theme] = deque(maxlen=HISTORY_LIMIT)
        return self.histories[theme]

    def _prompt(self, theme: str) -> str:
        overrides = self.cfg.get("prompts") or {}
        return overrides.get(theme) or PROMPTS.get(theme) or PROMPTS["default"]

    def ask(self, user_msg: str, theme: str = "default") -> str:
        history = self._history(theme)
        try:
            resp = self.client.messages.create(
                model=self.cfg["model"],
                max_tokens=MAX_TOKENS,
                system=self._prompt(theme),
                messages=list(history) + [{"role": "user", "content": user_msg}],
            )
        except anthropic.RateLimitError as e:
            raise ChatError("rate limited") from e
        except anthropic.AuthenticationError:
            raise ChatError("api key invalid") from None
        except anthropic.APIConnectionError as e:
            raise ChatError(f"network: {e}") from e
        except anthropic.APIStatusError as e:
            raise ChatError(f"HTTP {e.status_code}: {e.message}") from e

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": text})
        return text or "(empty reply)"


class ChatHandler(BaseHTTPRequestHandler):
    session: ChatSession | None = None  # set in main()

    # --- helpers ---
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    # --- methods ---
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/ping":
            self._json(200, {"ok": True, "model": self.session.cfg["model"], "busy": self.session.busy})
        elif self.path == "/api/config":
            cfg = self.session.cfg
            self._json(200, {
                "model": cfg["model"],
                "base_url": cfg["base_url"],
                "api_key_set": bool(cfg["api_key"]),
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/config":
            self._set_model()
            return
        if self.path != "/api/chat":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            message = str(body.get("message", "") or "").strip()
            # Unknown or absent theme -> "default", so an unmodified client
            # behaves exactly as before.
            theme = str(body.get("theme", "") or "").strip().lower()
            if theme not in PROMPTS:
                theme = "default"
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return
        if not message:
            self._json(400, {"error": "empty message"})
            return
        if len(message) > MAX_MESSAGE_CHARS:
            self._json(400, {"error": "message too long"})
            return
        if self.session.busy:
            self._json(429, {"error": "busy"})
            return
        if not self.session.cfg["api_key"]:
            self._json(500, {"error": "api key not configured"})
            return
        self.session.busy = True
        try:
            reply = self.session.ask(message, theme)
            self._json(200, {"reply": reply, "model": self.session.cfg["model"],
                             "theme": theme})
        except ChatError as e:
            self._json(502, {"error": str(e)})
        finally:
            self.session.busy = False

    def _set_model(self):
        """Change the model name. The only writable field — see docstring."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            model = str(body.get("model", "") or "").strip()
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return
        if not model:
            self._json(400, {"error": "empty model"})
            return
        if len(model) > MAX_MODEL_CHARS or any(c in model for c in "\r\n\t"):
            self._json(400, {"error": "invalid model name"})
            return
        self.session.cfg["model"] = model
        try:
            save_config({"model": model})
        except OSError as e:
            self._json(500, {"error": f"could not persist: {e}"})
            return
        self._json(200, {"ok": True, "model": model})


def main():
    ap = argparse.ArgumentParser(description="Local chat backend for the Device Monitor console")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()

    cfg = load_config()
    ChatHandler.session = ChatSession(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), ChatHandler)
    srv.allow_reuse_address = True

    key_status = "set" if cfg["api_key"] else "MISSING"
    print(f"[monitor-chat] base={cfg['base_url']} model={cfg['model']} key={key_status} "
          f"listening on 127.0.0.1:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("[monitor-chat] stopped")


if __name__ == "__main__":
    main()
