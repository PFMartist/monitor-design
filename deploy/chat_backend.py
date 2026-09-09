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
  POST /api/chat   -> {"message": "...", "reply": "..."} | {"error": "..."}
                     (429 busy, 400 bad input, 502 upstream error)
  POST /api/config -> {"model": "..."} -> {"ok": true, "model": ...}
                     Model name ONLY. base_url and api_key are deliberately
                     not writable over HTTP — the key must never reach the
                     browser (see above); change those in config.json.

Config (first hit wins):
  %APPDATA%/monitor_chat/config.json: {"base_url": ..., "api_key": ..., "model": ...}
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

SYSTEM_PROMPT = (
    "你是初音未来（Hatsune Miku），苍绿色双马尾的虚拟歌手。"
    "性格安静，带一点忧郁，用中文轻声交流。"
)


def config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "monitor_chat", "config.json")


def load_config() -> dict:
    cfg = {
        "base_url": os.environ.get("MONITOR_CHAT_BASE_URL", "https://api.anthropic.com"),
        "api_key": os.environ.get("MONITOR_CHAT_API_KEY", ""),
        "model": os.environ.get("MONITOR_CHAT_MODEL", "claude-sonnet-4-5"),
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
        self.history = deque(maxlen=HISTORY_LIMIT)  # [{"role","content"},...]
        self.lock = threading.Lock()
        self.client = anthropic.Anthropic(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            max_retries=1,
            timeout=REQUEST_TIMEOUT,
        )

    def _append(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def ask(self, user_msg: str) -> str:
        try:
            resp = self.client.messages.create(
                model=self.cfg["model"],
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=list(self.history) + [{"role": "user", "content": user_msg}],
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
        self._append("user", user_msg)
        self._append("assistant", text)
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
            reply = self.session.ask(message)
            self._json(200, {"reply": reply, "model": self.session.cfg["model"]})
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
