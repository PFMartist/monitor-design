#!/usr/bin/env python3
"""Device monitoring agent. Serves system and service metrics as JSON on :9090.
Reads service config from config.json; accepts POST /config from dashboard."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import socket
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

CREATE_NO_WINDOW = 0x08000000  # suppress PowerShell console popup

import psutil

# ---------------------------------------------------------------------------
# Config persistence (config.json)
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG: dict = {"services": {}}

_active_config: dict = {}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "services" not in cfg:
            cfg["services"] = {}
        return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        return {"services": {}}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def reload_config() -> dict:
    global _active_config
    _active_config = load_config()
    return _active_config


# ---------------------------------------------------------------------------
# Device identity (not tied to services)
# ---------------------------------------------------------------------------

def detect_device() -> str:
    return socket.gethostname().lower() or "device"


def resolve_device(cli_device: str | None) -> str:
    if cli_device:
        return cli_device
    env = os.environ.get("MONITOR_DEVICE")
    if env:
        return env
    return detect_device()


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------

def get_cpu() -> dict:
    cpu = psutil.cpu_percent(interval=0.1)
    return {
        "cpu_percent": round(cpu, 1),
        "cpu_count": psutil.cpu_count(logical=False),
        "cpu_count_logical": psutil.cpu_count(logical=True),
    }


def get_memory() -> dict:
    mem = psutil.virtual_memory()
    return {
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_percent": round(mem.percent, 1),
    }


def get_disks() -> list[dict]:
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        disks.append({
            "mount": part.mountpoint,
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "percent": round(usage.percent, 1),
        })
    return disks


def get_network() -> dict:
    # Sum per-interface so overlay traffic isn't double-counted: bytes sent
    # through ZeroTier/TAP appear on both the virtual and the physical NIC.
    sent = 0
    recv = 0
    for name, n in (psutil.net_io_counters(pernic=True) or {}).items():
        ln = name.lower()
        if ln == "lo" or "loopback" in ln or "zerotier" in ln:
            continue
        sent += n.bytes_sent
        recv += n.bytes_recv
    return {
        "network_bytes_sent": sent,
        "network_bytes_recv": recv,
    }


# Cache for slow metrics (PowerShell calls block the HTTP handler)
_temp_cache: dict | None = None
_temp_cache_time: float = 0
_gpu_cache: dict | None = None
_gpu_cache_time: float = 0
_ps_cache_valid: bool = False  # only True when PowerShell succeeded
CACHE_TTL = 120  # seconds — slow metrics only refresh every 2 min




def _collect_slow_metrics():
    """Single PowerShell call for ALL slow Windows metrics (temps + GPU).
    Updates global caches. Runs at most once per CACHE_TTL seconds.
    Cache only set on SUCCESSFUL run — failures retry on next request."""
    global _temp_cache, _temp_cache_time, _gpu_cache, _gpu_cache_time, _ps_cache_valid
    now = time.time()
    if _temp_cache_time > 0 and (now - _temp_cache_time) < CACHE_TTL:
        return  # rate-limit: don't retry within CACHE_TTL

    cpu_temp = None
    gpu_temp = None
    gpu_pct = None
    gpu_mem = None

    # Single PowerShell call for WMI temps + GPU perf counters
    ps_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slow_metrics.ps1")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_file],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                if line.startswith("TZ|"):
                    parts = line.split("|")
                    if len(parts) >= 3:
                        inst, val = parts[1], float(parts[2])
                        il = inst.lower()
                        if cpu_temp is None and "cpu" not in il and "gpu" not in il:
                            cpu_temp = val
                        if gpu_temp is None and "gpu" in il:
                            gpu_temp = val
                elif line.startswith("GPU|"):
                    parts = line.split("|")
                    if len(parts) >= 3:
                        gpu_pct = min(float(parts[1]) if parts[1] else 0.0, 100.0)
                        gpu_mem = float(parts[2]) if parts[2] else 0.0
    except subprocess.TimeoutExpired:
        pass  # PowerShell timed out — metrics unavailable this cycle
    except Exception as e:
        pass  # PowerShell error — metrics unavailable this cycle

    # nvidia-smi GPU temp fallback
    if gpu_temp is None:
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0 and r.stdout.strip():
                gpu_temp = float(r.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, OSError, FileNotFoundError):
            pass

    # Rate-limit next retry regardless of outcome
    _temp_cache_time = now

    # Only update caches that have new valid data (keep old values on failure)
    if cpu_temp is not None or gpu_temp is not None:
        _temp_cache = {"cpu": cpu_temp, "gpu": gpu_temp}
    if gpu_pct is not None or gpu_mem is not None:
        _gpu_cache = {"gpu_percent": gpu_pct, "gpu_memory_bytes": gpu_mem}
        _gpu_cache_time = now


def get_temperatures() -> dict:
    _collect_slow_metrics()
    cpu = _temp_cache["cpu"] if _temp_cache else None
    gpu = _temp_cache["gpu"] if _temp_cache else None

    # psutil temps (always fresh, no subprocess)
    try:
        st = psutil.sensors_temperatures()
    except AttributeError:
        st = {}
    if st:
        for _, entries in st.items():
            for e in entries:
                lbl = e.label.lower() if e.label else ""
                if cpu is None and any(k in lbl for k in ("package", "core", "cpu")):
                    cpu = e.current
                if gpu is None and any(k in lbl for k in ("gpu", "nvidia", "radeon")):
                    gpu = e.current
        if cpu is None:
            for _, entries in st.items():
                if entries:
                    cpu = entries[0].current
                    break

    return {"cpu": cpu, "gpu": gpu}


def get_gpu_usage() -> dict:
    _collect_slow_metrics()
    return _gpu_cache if _gpu_cache is not None else {"gpu_percent": None, "gpu_memory_bytes": None}


# ---------------------------------------------------------------------------
# Service checks
# ---------------------------------------------------------------------------

import glob
import hashlib
import http.cookiejar
import re
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64encode
from pathlib import Path

# urllib consults the Windows proxy settings on every request, and CPython's
# bypass check (urllib.request.proxy_bypass_registry) calls socket.getfqdn() —
# a reverse DNS lookup — before the request even goes out. Loopback answers
# instantly from the hosts file, but anything else waits out the resolver:
# measured ~4.6 s against api.deepseek.com and ~4.9 s against a LAN address on
# this network. An empty ProxyHandler means the system proxy is never consulted
# at all, which is what these checks want anyway — they talk to loopback or
# straight to the internet, never through a proxy.
#
# (Every check happened to use 127.0.0.1, so the cost was invisible until the
# first check that addressed something else.)
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CHECK_TIMEOUT = 3


def check_port(host: str, port: int) -> dict:
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return {"online": True, "port_open": True}
    except OSError:
        return {"online": False, "port_open": False}


_proc_cache: set[str] = set()
_proc_cache_time: float = 0
# Command lines cost far more to collect than image names, so they get their own
# cache and are only gathered when a check actually asks for a cmdline match.
_proc_cmdlines: list[tuple[str, str]] = []
_proc_cmdlines_time: float = 0


def _process_names() -> set[str]:
    global _proc_cache, _proc_cache_time
    now = time.time()
    if now - _proc_cache_time > 5:  # refresh once per poll cycle
        names = set()
        for p in psutil.process_iter(["name"]):
            try:
                names.add(p.name().lower())
            except Exception:
                pass
        _proc_cache = names
        _proc_cache_time = now
    return _proc_cache


def _process_cmdlines() -> list[tuple[str, str]]:
    """(image name, command line) pairs, both lowercased.

    Kept as pairs rather than a flat list of command lines so a cmdline match
    can still be tied to the image it belongs to — matching the command line
    alone would let any process satisfy the check.
    """
    global _proc_cmdlines, _proc_cmdlines_time
    now = time.time()
    if now - _proc_cmdlines_time > 5:
        rows = []
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                nm = (p.info.get("name") or "").lower()
                cl = p.info.get("cmdline")
                if nm and cl:
                    rows.append((nm, " ".join(cl).lower()))
            except Exception:
                pass
        _proc_cmdlines = rows
        _proc_cmdlines_time = now
    return _proc_cmdlines


def check_process(process_name: str, cmdline_match: str | None = None) -> dict:
    """Process presence by image name, optionally narrowed by its command line.

    cmdline_match exists because some tools run under a generic image name:
    happy's daemon is just `node.exe`, so matching on the name alone would light
    up for any Node process on the box. Both conditions must hold for the same
    process, not one process each.
    """
    name = process_name.lower()
    if cmdline_match:
        needle = cmdline_match.lower()
        found = any(nm == name and needle in cl for nm, cl in _process_cmdlines())
    else:
        found = name in _process_names()
    return {"online": found, "process_running": found}


def _find_latest_log(log_dir: str, log_glob: str) -> Path | None:
    pattern = str(Path(log_dir) / log_glob)
    files = glob.glob(pattern)
    if not files:
        return None
    return Path(max(files, key=os.path.getmtime))


def _tail_log(path: Path, max_bytes: int = 8192) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read_size = min(size, max_bytes)
            start = max(0, size - read_size)
            f.seek(start)
            raw = f.read(read_size)
            # A tail window can begin in the middle of a UTF-8 character or
            # log line. Discard that partial line before decoding.
            if start > 0:
                newline = raw.find(b"\n")
                if newline >= 0:
                    raw = raw[newline + 1:]
            for enc in ("utf-8", "gbk", "gb2312"):
                try:
                    return raw.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _tail_log_until(path: Path, pattern: re.Pattern[str],
                    initial_bytes: int = 32768,
                    max_bytes: int = 4 * 1024 * 1024) -> str:
    """Grow a tail window until pattern is found or the safety cap is reached."""
    try:
        file_size = path.stat().st_size
    except OSError:
        return ""
    if file_size <= 0:
        return ""

    limit = min(file_size, max_bytes)
    read_size = min(initial_bytes, limit)
    while True:
        text = _tail_log(path, max_bytes=read_size)
        if pattern.search(text) or read_size >= limit:
            return text
        read_size = min(read_size * 2, limit)


def check_maa(process_name: str, log_dir: str, log_glob: str) -> dict:
    proc = check_process(process_name)
    result: dict = {
        "online": proc["process_running"],
        "process_running": proc["process_running"],
        "last_task_time_iso": None,
        "last_task_age_seconds": None,
        "last_task_status": None,
        "last_task_name": None,
    }

    log_path = _find_latest_log(log_dir, log_glob)
    if log_path is None:
        return result

    # gui.log format:
    # [2026-05-26 16:44:53.877][INF]... Idle: true to false (called from ...
    # [2026-05-26 16:44:53.883][INF]... 开始任务: 生息演算
    # [2026-09-02 18:02:56.099][INF]... Start Task Chain: Fight, Task ID: 9
    # [2026-05-26 17:09:53.891][WRN]... 已超过 25 分钟无更新（当前已停滞...）

    ts_pat = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]")
    idle_to_true  = re.compile(r"Idle:\s*false\s*to\s*true")
    idle_to_false = re.compile(r"Idle:\s*true\s*to\s*false")
    idle_transition = re.compile(r"Idle:\s*(?:false\s*to\s*true|true\s*to\s*false)")
    task_pat = re.compile(r"开始任务:\s*(.+)")
    chain_start_pat = re.compile(r"Start Task Chain:\s*([^,\r\n]+)")
    completed_pat = re.compile(r"完成任务:\s*(.+)")
    stuck_pat = re.compile(r"(\d+)\s*分钟无更新")
    # Task queue snapshot: Index 0, Type "StartUp", Name 开始唤醒, IsEnable true
    queue_pat = re.compile(
        r'Index\s+(\d+),\s*Type "([^"]+)".*Name ([^,]+).*IsEnable (true|false)'
    )

    # Long HTTP request bodies can push the latest Idle boundary beyond 32 KB.
    # Grow only as far as needed instead of reading an unbounded gui.log.
    tail = _tail_log_until(log_path, idle_transition)

    reversed_lines = tail.splitlines()[::-1]
    idle_boundary_seen = False
    current_task_type: str | None = None
    last_completed_name: str | None = None
    queue_names: dict[str, str] = {}
    enabled_queue: list[tuple[int, str]] = []

    for line in reversed_lines:
        # Idle state
        if result["last_task_status"] is None:
            if idle_to_true.search(line):
                sm = stuck_pat.search(line)
                if sm:
                    result["last_task_status"] = "stuck_" + sm.group(1) + "m"
                else:
                    result["last_task_status"] = "idle"
            elif idle_to_false.search(line):
                result["last_task_status"] = "running"

        # Task name (only accept from current run; block stale ones from before Idle transition)
        if not idle_boundary_seen:
            if current_task_type is None:
                m = chain_start_pat.search(line)
                if m:
                    current_task_type = m.group(1).strip()

            if result["last_task_name"] is None:
                m = task_pat.search(line)
                if m:
                    result["last_task_name"] = m.group(1).strip()

            if last_completed_name is None:
                m = completed_pat.search(line)
                if m:
                    last_completed_name = m.group(1).strip()

            m = queue_pat.search(line)
            if m and m.group(4) == "true":
                index = int(m.group(1))
                task_type = m.group(2)
                task_name = m.group(3).strip()
                queue_names.setdefault(task_type, task_name)
                enabled_queue.append((index, task_name))

        if idle_to_true.search(line) or idle_to_false.search(line):
            idle_boundary_seen = True

        # Timestamp
        if result["last_task_time_iso"] is None:
            m = ts_pat.search(line)
            if m:
                ts_str = m.group(1)
                try:
                    ts_clean = ts_str.split(".")[0]
                    ts_struct = time.strptime(ts_clean, "%Y-%m-%d %H:%M:%S")
                    result["last_task_time_iso"] = ts_str.replace(" ", "T")
                    result["last_task_age_seconds"] = int(time.time() - time.mktime(ts_struct))
                except ValueError:
                    pass

        if idle_boundary_seen and result["last_task_status"] and result["last_task_time_iso"]:
            break

    if result["last_task_name"] is None:
        if current_task_type is not None:
            result["last_task_name"] = queue_names.get(current_task_type, current_task_type)
        elif last_completed_name is not None:
            result["last_task_name"] = last_completed_name
        elif enabled_queue:
            result["last_task_name"] = min(enabled_queue)[1]

    return result


def _maaend_result(process_running: bool = False) -> dict:
    return {
        "online": process_running,
        "process_running": process_running,
        "last_task_time_iso": None,
        "last_task_age_seconds": None,
        "last_task_status": None,
        "last_task_name": None,
    }


def _set_maaend_timestamp(result: dict, ts_str: str, ts_format: str) -> None:
    try:
        ts_struct = time.strptime(ts_str, ts_format)
        result["last_task_time_iso"] = ts_str.replace(" ", "T")
        result["last_task_age_seconds"] = int(time.time() - time.mktime(ts_struct))
    except ValueError:
        pass


def _parse_maaend_gui_log(text: str) -> dict:
    """Parse MXU GUI logs named YYYY-MM-DD-<launch index>.log."""
    result = _maaend_result()
    event_pat = re.compile(
        r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+'
        r'\w+\s+\[App\].*\bkind:\s*'
        r'(task-started|task-stopped|task-progress|tasks-completed)\b'
    )
    task_name_pat = re.compile(r'\[Task\]\s+实例\s+(.+?):\s')
    status_by_event = {
        "task-started": "running",
        "task-progress": "running",
        "task-stopped": "idle",
        "tasks-completed": "idle",
    }

    for line in reversed(text.splitlines()):
        if result["last_task_name"] is None:
            name_m = task_name_pat.search(line)
            if name_m:
                result["last_task_name"] = name_m.group(1).strip()

        if result["last_task_status"] is None:
            event_m = event_pat.match(line)
            if event_m:
                result["last_task_status"] = status_by_event[event_m.group(2)]
                _set_maaend_timestamp(result, event_m.group(1), "%Y-%m-%d %H:%M:%S")

        if result["last_task_status"] and result["last_task_name"]:
            break

    return result


def _parse_maaend_maafw_log(text: str) -> dict:
    """Parse legacy MaaFramework logs containing Tasker.Task callbacks."""
    result = _maaend_result()
    ts_pat = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
    evt_pat = re.compile(r'Tasker\.Task\.(Starting|Succeeded|Failed)')
    entry_pat = re.compile(r'"entry"\s*:\s*"([^"]+)"')

    for line in reversed(text.splitlines()):
        evt_m = evt_pat.search(line)
        if not evt_m:
            continue
        evt = evt_m.group(1)
        if evt == "Starting":
            result["last_task_status"] = "running"
        elif evt == "Succeeded":
            result["last_task_status"] = "idle"
        else:
            result["last_task_status"] = "failure"
        entry_m = entry_pat.search(line)
        if entry_m:
            result["last_task_name"] = entry_m.group(1)
        ts_m = ts_pat.search(line)
        if ts_m:
            ts_str = ts_m.group(1)
            _set_maaend_timestamp(result, ts_str, "%Y-%m-%d %H:%M:%S.%f")
        break
    return result


def check_maaend(process_name: str, log_dir: str, log_glob: str) -> dict:
    """MaaEnd (Endfield) — parses MXU GUI logs or legacy maafw.log."""
    proc = check_process(process_name)
    result = _maaend_result(proc["process_running"])

    log_path = _find_latest_log(log_dir, log_glob)
    if log_path is None:
        return result

    # MXU GUI logs are small daily/per-launch files. Keep enough history to
    # survive the scheduler's once-per-minute messages after the last task.
    is_dated_gui_log = bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}-\d+\.log', log_path.name))
    text = _tail_log(log_path, max_bytes=512 * 1024 if is_dated_gui_log else 32768)

    # Route by the line prefix so custom globs or names remain compatible.
    # GUI lines start with a bare timestamp; MaaFramework lines use [..].
    is_gui_format = any(
        re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s', line)
        for line in text.splitlines()
    )
    parsed = _parse_maaend_gui_log(text) if is_gui_format else _parse_maaend_maafw_log(text)
    parsed["online"] = proc["process_running"]
    parsed["process_running"] = proc["process_running"]
    return parsed


# ---------------------------------------------------------------------------
# MAA recruit alerts — persisted counter, cleared manually from the dashboard
# ---------------------------------------------------------------------------

ALERTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maa_alerts.json")

# (core callback `what`, details.tag, label shown in the dashboard)
# The middle field must stay as the game writes it — it's matched against log
# text. Only the label is ours, and it uses the official English tag names.
_ALERT_TAGS: tuple[tuple[str, str, str], ...] = (
    ("RecruitSpecialTag", "高级资深干员", "6★"),
    ("RecruitPreservedTag", "支援机械", "Robot"),
)


def _alerts_default() -> dict:
    return {"count": 0, "kinds": [], "offset": 0, "last_seen": None}


def _load_alerts() -> dict:
    try:
        with open(ALERTS_PATH, "r", encoding="utf-8") as f:
            stored = json.load(f)
        if not isinstance(stored, dict):
            raise ValueError("not an object")
        return {**_alerts_default(), **stored}
    except (OSError, ValueError):
        return _alerts_default()


def _save_alerts(alerts: dict) -> None:
    try:
        with open(ALERTS_PATH, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def alerts_view(alerts: dict) -> dict:
    """Dashboard-facing shape. The raw count stays internal — the frontend only
    shows *which* kinds are pending, not how many."""
    return {
        "online": True,
        "count": int(alerts.get("count") or 0),
        "kinds": list(alerts.get("kinds") or []),
        "last_seen": alerts.get("last_seen"),
    }


def clear_alerts() -> dict:
    alerts = _load_alerts()
    alerts["count"] = 0
    alerts["kinds"] = []
    _save_alerts(alerts)
    return {"ok": True, **alerts_view(alerts)}


def check_maa_alerts(log_dir: str, log_glob: str,
                     max_read: int = 4 * 1024 * 1024) -> dict:
    """Count new recruit callbacks in MAA's core log (asst.log).

    The file is consumed incrementally: the byte offset past the last complete
    line is persisted, so agent restarts never re-count old events. A file
    smaller than the saved offset means MAA rotated it — restart from 0.

    Signals are core callbacks, matched on `what` + `details.tag`:
      RecruitSpecialTag   + 高级资深干员 → 6★ (MAA leaves it unconfirmed)
      RecruitPreservedTag + 支援机械    → preserved for manual handling
    RecruitSpecialTag also fires for 资深干员 (5★, auto-recruited normally), so
    the tag match is what keeps 5★ out of the count.
    """
    first_run = not os.path.exists(ALERTS_PATH)
    alerts = _load_alerts()
    path = _find_latest_log(log_dir, log_glob)
    if path is None:
        return {**alerts_view(alerts), "online": False}
    try:
        size = path.stat().st_size
    except OSError:
        return {**alerts_view(alerts), "online": False}

    # First ever run: start at the current end of the log. Scanning from 0 would
    # count every historical detection the moment the service is added.
    if first_run:
        alerts["offset"] = size
        _save_alerts(alerts)
        return alerts_view(alerts)

    offset = int(alerts.get("offset") or 0)
    if size < offset:
        offset = 0  # rotated or truncated

    if size > offset:
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                raw = f.read(max_read)
        except OSError:
            raw = b""
        # Consume whole lines only — a half-written tail waits for the next poll.
        cut = raw.rfind(b"\n")
        if cut >= 0:
            raw = raw[: cut + 1]
            offset += len(raw)
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if '"what":"Recruit' not in line:
                    continue
                for what, tag, label in _ALERT_TAGS:
                    if f'"what":"{what}"' in line and f'"tag":"{tag}"' in line:
                        alerts["count"] = int(alerts.get("count") or 0) + 1
                        if label not in alerts["kinds"]:
                            alerts["kinds"].append(label)
                        alerts["last_seen"] = line[1:20] if line.startswith("[") else None
                        break
        alerts["offset"] = offset
        _save_alerts(alerts)

    return alerts_view(alerts)


# Images the happy daemon can legitimately appear as: happy is a JS CLI, so the
# process is `node.exe` (or bun with --js-runtime bun), never "happy".
_HAPPY_IMAGES = {"node", "node.exe", "bun", "bun.exe", "happy", "happy.exe"}

# The daemon heartbeats while alive; anything older than this means it is gone
# even if the recorded pid now belongs to some other process.
_HAPPY_HEARTBEAT_MAX_AGE = 3600  # seconds


def _parse_happy_time(value) -> float | None:
    """Happy timestamps look like "2026/9/7 23:02:02" (not zero-padded)."""
    if not isinstance(value, str):
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(value, fmt))
        except ValueError:
            continue
    return None


def check_happy(home_dir: str | None = None) -> dict:
    """Happy daemon status, read straight from the daemon's own state file.

    Deliberately NOT `happy daemon status`: that spawns Node, measures ~1.9s per
    call and writes a log line each run — untenable on a 5s poll. The CLI's own
    liveness check is exactly "read daemon.state.json, is that pid alive?", which
    this reproduces in about a millisecond.

    Coupled to the state file's shape (happy 1.1.x): pid / httpPort / version /
    startedAt. Anything missing degrades to null rather than raising.
    """
    result = {
        "online": False, "running": False, "stale": False,
        "pid": None, "http_port": None, "version": None, "started_at": None,
        "last_heartbeat_age_seconds": None,
    }
    # Mirrors happy's own resolution: HAPPY_HOME_DIR *is* the happy dir (not its
    # parent), otherwise ~/.happy. Accepts a leading "~" like happy does.
    base = (home_dir or os.environ.get("HAPPY_HOME_DIR")
            or os.path.join(os.path.expanduser("~"), ".happy"))
    state_path = os.path.join(os.path.expanduser(base), "daemon.state.json")

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return result  # never started, or stopped cleanly (state file removed)
    if not isinstance(state, dict):
        return result

    pid = state.get("pid")
    result["pid"] = pid
    result["http_port"] = state.get("httpPort")
    # Key names as actually written by happy 1.x (verified against a live state
    # file): startedWithCliVersion / startTime. The shorter spellings are kept as
    # fallbacks in case a build renames them.
    result["version"] = state.get("startedWithCliVersion") or state.get("version")
    result["started_at"] = state.get("startTime") or state.get("startedAt")

    hb = _parse_happy_time(state.get("lastHeartbeat"))
    if hb is not None:
        result["last_heartbeat_age_seconds"] = int(time.time() - hb)

    alive = False
    if isinstance(pid, int) and pid > 0:
        try:
            proc = psutil.Process(pid)
            # A recycled PID would read as "running" forever, so also require the
            # image to still look like a JS runtime.
            alive = proc.is_running() and (proc.name() or "").lower() in _HAPPY_IMAGES
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            alive = False

    # A long-silent heartbeat overrides a live-looking pid — the strongest signal
    # available, since pid recycling is common on a dev box.
    age = result["last_heartbeat_age_seconds"]
    if alive and age is not None and age > _HAPPY_HEARTBEAT_MAX_AGE:
        alive = False

    result["running"] = alive
    result["online"] = alive
    # State file present but its pid is gone — happy reports this as "stale".
    result["stale"] = not alive
    return result


def check_adguard(api_url: str) -> dict:
    result = {"online": False, "queries_total": None, "blocked_total": None, "avg_processing_time_ms": None}
    user = os.environ.get("ADGUARD_USER", "admin")
    password = os.environ.get("ADGUARD_PASS", "")
    try:
        url = f"{api_url.rstrip('/')}/control/stats"
        req = urllib.request.Request(url)
        if password:
            creds = b64encode(f"{user}:{password}".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
        with _NO_PROXY_OPENER.open(req, timeout=CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read())
            result["online"] = True
            result["queries_total"] = data.get("num_dns_queries")
            result["blocked_total"] = data.get("num_blocked_filtering")
            result["avg_processing_time_ms"] = round(data.get("avg_processing_time", 0) * 1000, 1)
    except Exception:
        pass
    return result


def check_syncthing(api_url: str) -> dict:
    result = {"online": False, "pending_files": None, "connected_devices": None, "error_message": None}
    api_key = os.environ.get("SYNCTHING_KEY", "")
    base = api_url.rstrip("/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if api_key:
        opener.addheaders = [("X-API-Key", api_key)]

    # Enumerate ALL folders — devices rarely have one named "default", so a
    # single ?folder=default probe misses real sync backlog.
    folder_ids: list[str] = []
    api_reachable = False
    try:
        with opener.open(f"{base}/rest/config/folders", timeout=CHECK_TIMEOUT) as resp:
            folder_ids = [f.get("id") for f in json.loads(resp.read()) if f.get("id")]
            api_reachable = True
    except Exception:
        pass
    if not api_reachable:  # legacy endpoint for older Syncthing
        try:
            with opener.open(f"{base}/rest/system/config", timeout=CHECK_TIMEOUT) as resp:
                folder_ids = [f.get("id") for f in json.loads(resp.read()).get("folders", []) if f.get("id")]
                api_reachable = True
        except Exception:
            pass
    if not folder_ids:
        folder_ids = ["default"]

    pending = 0
    any_status_ok = False
    for folder_id in folder_ids:
        try:
            with opener.open(
                f"{base}/rest/db/status?folder={urllib.parse.quote(folder_id)}",
                timeout=CHECK_TIMEOUT,
            ) as resp:
                pending += json.loads(resp.read()).get("needTotalItems", 0) or 0
                any_status_ok = True
        except Exception:
            continue

    if api_reachable or any_status_ok:
        result["online"] = True
        if any_status_ok:
            result["pending_files"] = pending
        elif not folder_ids:  # API up, zero folders configured
            result["pending_files"] = 0
    else:
        result["error_message"] = "syncthing API unreachable"

    # Connected devices via /rest/system/connections (v2+)
    try:
        with opener.open(f"{base}/rest/system/connections", timeout=CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read())
            conns = data.get("connections", {})
            connected = sum(1 for c in conns.values() if c.get("connected"))
            result["connected_devices"] = connected
    except Exception:
        pass

    return result


def check_utorrent(api_url: str) -> dict:
    result = {"online": False, "download_speed_bytes": None, "upload_speed_bytes": None, "active_count": None}
    user = os.environ.get("UTORRENT_USER", "admin")
    password = os.environ.get("UTORRENT_PASS", "")
    try:
        base = api_url.rstrip("/")
        token_url = f"{base}/gui/token.html"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if password:
            creds = b64encode(f"{user}:{password}".encode()).decode()
            opener.addheaders = [("Authorization", f"Basic {creds}")]
        with opener.open(token_url, timeout=CHECK_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        token_match = re.search(r"id=['\"]token['\"]\s*[^>]*>([^<]+)<", html)
        token = token_match.group(1) if token_match else ""

        list_url = f"{base}/gui/?token={token}&list=1"
        req = urllib.request.Request(list_url)
        if password:
            req.add_header("Authorization", f"Basic {creds}")
        with _NO_PROXY_OPENER.open(req, timeout=CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read())
            result["online"] = True
            torrents = data.get("torrents", [])
            dl_total = sum(t[9] for t in torrents if len(t) > 9)
            ul_total = sum(t[8] for t in torrents if len(t) > 8)
            active = sum(1 for t in torrents if len(t) > 9 and (t[8] > 0 or t[9] > 0))
            result["download_speed_bytes"] = dl_total
            result["upload_speed_bytes"] = ul_total
            result["active_count"] = active
    except Exception as e:
        result["error_message"] = str(e)[:200]
    return result


def check_webdav(url: str) -> dict:
    result = {"online": False, "status_code": None, "response_time_ms": None}
    try:
        t0 = time.perf_counter()
        req = urllib.request.Request(url, method="HEAD")
        with _NO_PROXY_OPENER.open(req, timeout=CHECK_TIMEOUT) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            result["online"] = resp.status < 500
            result["status_code"] = resp.status
            result["response_time_ms"] = elapsed
    except urllib.error.HTTPError as e:
        result["online"] = e.code < 500
        result["status_code"] = e.code
        result["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    except Exception as e:
        result["error_message"] = str(e)[:200]
    return result


# ---------------------------------------------------------------------------
# Account balance / quota
# ---------------------------------------------------------------------------
# The only checks that leave the LAN: they report an *account's* credit, not a
# machine's health. That changes two things.
#
#   * They're cached for minutes, not seconds. The dashboard polls every few
#     seconds and a balance doesn't move that fast.
#   * Failures are cached too, briefly — otherwise a revoked key turns every
#     dashboard poll into an outbound request.
#
# Keys are read from the environment and never returned to the dashboard; the
# result only says whether a key was found.

BALANCE_TTL = 300       # seconds a good reading is reused
BALANCE_ERROR_TTL = 30  # ...and a failed one, so we don't hammer the API
BALANCE_TIMEOUT = 8     # local checks get 3 s; TLS to a vendor CDN needs more

_balance_cache: dict[str, tuple[float, dict]] = {}


def _key_fingerprint(key: str) -> str:
    """Cache identity has to move when the key does, or a swapped account keeps
    serving the previous one's numbers until the TTL expires."""
    return hashlib.sha256(key.encode()).hexdigest()[:12] if key else "none"


def _cached_balance(cache_key: str, fetch) -> dict:
    now = time.time()
    hit = _balance_cache.get(cache_key)
    if hit:
        # A stale reading is kept visible but retried on the short TTL, so
        # recovery doesn't wait out the full 5 minutes.
        fresh = hit[1].get("online") and not hit[1].get("stale")
        ttl = BALANCE_TTL if fresh else BALANCE_ERROR_TTL
        if (now - hit[0]) < ttl:
            return hit[1]

    result = fetch()
    result["fetched_at"] = round(now, 3)
    prev = hit[1] if hit else None

    # A transport failure keeps the last reading on screen, flagged stale — the
    # bar is polled every few seconds and a blank cell reads as "no data".
    # An auth failure is not a blip: those numbers describe an account you can
    # no longer use, so it invalidates instead of lingering.
    if (prev and (prev.get("online") or prev.get("stale"))
            and not result.get("online") and result.get("error_code") == "network"):
        stale = dict(prev)
        stale["stale"] = True
        stale["error_code"] = "stale"
        stale["error_message"] = result.get("error_message")
        stale["fetched_at"] = prev.get("fetched_at", now)  # last SUCCESS, not this attempt
        result = stale
    else:
        result["stale"] = False

    _balance_cache[cache_key] = (now, result)
    return result


class _BlockedError(Exception):
    """Edge/WAF rejection (Cloudflare 1010 and friends). Not a key problem and
    not retryable — telling them apart matters, because "your key is wrong" and
    "the CDN won't talk to this HTTP client" want different fixes."""


def _curl_get(url: str, key: str) -> dict:
    """GET via curl.exe, for the vendors whose edge rejects Python's TLS
    fingerprint. opencode.ai answers urllib with Cloudflare 1010 before auth is
    even considered, while curl.exe sails through — which is why the ecosystem
    plugins shell out to curl for this endpoint too.

    The key rides in a config on stdin (`-K -`), never in argv: a command line
    is readable by any process running as the same user.
    """
    cfg = (
        f'url = "{url}"\n'
        f'header = "Authorization: Bearer {key}"\n'
        f'header = "Accept: application/json"\n'
        f'silent\nshow-error\nmax-time = {BALANCE_TIMEOUT}\n'
        f'write-out = "\\n%{{http_code}}"\n'
    )
    try:
        r = subprocess.run(
            ["curl.exe", "-K", "-"], input=cfg, capture_output=True, text=True,
            errors="replace", timeout=BALANCE_TIMEOUT + 5,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        raise RuntimeError("curl.exe not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise TimeoutError("curl timed out") from None

    body, _, code = r.stdout.rpartition("\n")
    code = code.strip()
    if not code.isdigit():
        raise RuntimeError((r.stderr or "curl returned no status").strip()[:200])
    if not code.startswith("2"):
        if "cloudflare" in body.lower() or "browser_signature_banned" in body:
            raise _BlockedError(f"edge blocked the request (HTTP {code})")
        raise urllib.error.HTTPError(url, int(code), f"HTTP {code}", None, None)
    return json.loads(body)


def _bearer_get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })
    with _NO_PROXY_OPENER.open(req, timeout=BALANCE_TIMEOUT) as resp:
        return json.loads(resp.read())


def _balance_error(result: dict, e: Exception) -> dict:
    """One place that turns a failure into a stable code the dashboard can
    branch on, plus the full text for the row's tooltip."""
    if isinstance(e, urllib.error.HTTPError):
        result["error_code"] = f"http_{e.code}"  # 401 = bad key, 403 = no plan
        result["error_message"] = f"HTTP {e.code}"
    elif isinstance(e, _BlockedError):
        result["error_code"] = "blocked"
        result["error_message"] = str(e)
    elif isinstance(e, json.JSONDecodeError):
        result["error_code"] = "bad_response"
        result["error_message"] = "response was not JSON"
    else:
        result["error_code"] = "network"
        result["error_message"] = str(e)[:200]
    return result


CHAT_CONFIG_PATH = os.path.join(
    os.environ.get("APPDATA", ""), "monitor_chat", "config.json"
)


def _deepseek_key() -> str:
    """Env var first, else the chat backend's config — it's the same key, and
    keeping one copy means it can't drift. The chat backend lives on Main only,
    so on other devices this is env-var or nothing."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    try:
        with open(CHAT_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("api_key", "") or ""
    except Exception:
        return ""


# The hosts below are deliberately NOT configurable, unlike every other check's
# URL. These two requests carry an Authorization header, and the agent takes
# POST /config from anyone who can reach the port — a configurable URL would let
# that anyone point the check at a server they control and harvest the key.
# A mirror/proxy would have to be a code change here, not a config edit.
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


def check_deepseek(low_balance: float | None = None) -> dict:
    # Key fingerprint and low_balance are both in the cache key: the first so a
    # swapped key can't inherit the old account's numbers, the second so an
    # edit in the dashboard lands on the next poll instead of up to TTL later.
    key = _deepseek_key()
    return _cached_balance(
        f"deepseek:{_key_fingerprint(key)}:{low_balance}",
        lambda: _fetch_deepseek(key, low_balance),
    )


def _fetch_deepseek(key: str, low_balance: float | None) -> dict:
    result = {
        "online": False, "balance": None, "currency": None,
        "granted_balance": None, "topped_up_balance": None,
        "is_available": None, "level": "ok",
        "error_code": None, "error_message": None,
    }
    if not key:
        result["error_code"] = "no_key"
        result["error_message"] = "DEEPSEEK_API_KEY not set (and no chat config)"
        return result
    try:
        data = _bearer_get(DEEPSEEK_BALANCE_URL, key)
    except Exception as e:
        return _balance_error(result, e)

    # One entry per currency; a top-up account has exactly one.
    infos = data.get("balance_infos") or []
    if not infos:
        result["error_code"] = "bad_response"
        result["error_message"] = "no balance_infos in response"
        return result
    info = next((i for i in infos if i.get("currency") == "CNY"), infos[0])
    result.update(
        online=True,
        balance=info.get("total_balance"),
        currency=info.get("currency"),
        granted_balance=info.get("granted_balance"),
        topped_up_balance=info.get("topped_up_balance"),
        is_available=data.get("is_available"),
    )
    # is_available is the vendor's own "can this account still make calls" —
    # a harder signal than any threshold we'd pick, so it wins.
    if result["is_available"] is False:
        result["level"] = "bad"
        return result
    # Off by default — "low" depends on how fast you burn it, so the threshold
    # comes from the service config rather than a guess baked in here.
    try:
        if low_balance is not None and float(result["balance"]) <= float(low_balance):
            result["level"] = "warn"
    except (TypeError, ValueError):
        pass
    return result


# opencode.ai/zen/go is the subscription gateway ("OpenCode Go"): no balance,
# just three rolling allowance windows. The endpoint is undocumented — only
# /v1/usage answers, everything else 404s — so the window keys are matched a
# little leniently rather than pinned to one spelling.
OPENCODE_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
OPENCODE_WINDOWS = ("rolling", "weekly", "monthly")
OPENCODE_WINDOW_ALIASES = {
    "rolling": ("rolling", "5h", "hourly", "short"),
    "weekly": ("weekly", "week", "wk"),
    "monthly": ("monthly", "month", "mo"),
}
QUOTA_WARN_PERCENT = 65  # same yellow threshold the metric bars use


CLAUDE_SETTINGS_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "settings.json"
)
OPENCODE_GATEWAY_HOST = "opencode.ai"


def _key_from_claude_settings() -> str:
    """cc-switch materialises the active provider into the *tool's* own config
    rather than making tools read its database, so while Claude Code is pointed
    at the opencode gateway its key is sitting right there.

    The base-URL guard is the load-bearing part: flip cc-switch to another
    provider and that same field holds a foreign key, which must never be sent
    to opencode.ai. Guard fails → no key → the bar says so, instead of quietly
    querying someone else's account.
    """
    try:
        with open(CLAUDE_SETTINGS_PATH, encoding="utf-8") as f:
            env = json.load(f).get("env") or {}
    except Exception:
        return ""
    u = urllib.parse.urlparse(env.get("ANTHROPIC_BASE_URL", ""))
    # https is required: over plain http this would put the key on the wire in
    # cleartext. Host must match exactly — "opencode.ai.evil.com" parses to a
    # different netloc, so the equality check already rejects it.
    if u.scheme != "https" or u.netloc != OPENCODE_GATEWAY_HOST:
        return ""
    return env.get("ANTHROPIC_API_KEY", "") or ""


def _opencode_key() -> str:
    """Both env names are accepted because the surrounding tooling split on
    them: OPENCODE_GO_API_KEY is what the plugin ecosystem asks for, and
    OPENCODE_API_KEY is what this machine's dsh config declares."""
    for name in ("OPENCODE_API_KEY", "OPENCODE_GO_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    return _key_from_claude_settings()


def check_opencode() -> dict:
    key = _opencode_key()
    return _cached_balance(
        f"opencode:{_key_fingerprint(key)}", lambda: _fetch_opencode(key)
    )


def _fetch_opencode(key: str) -> dict:
    result = {
        "online": False, "level": "ok", "worst_percent": None,
        "error_code": None, "error_message": None,
    }
    for window in OPENCODE_WINDOWS:
        result[f"{window}_percent"] = None
        result[f"{window}_status"] = None
        result[f"{window}_resets_at"] = None

    if not key:
        result["error_code"] = "no_key"
        result["error_message"] = "OPENCODE_API_KEY not set (and Claude Code isn't on the opencode gateway)"
        return result
    try:
        data = _curl_get(OPENCODE_USAGE_URL, key)
    except Exception as e:
        return _balance_error(result, e)  # 401 = bad key, 403 = no Go plan

    usage = data.get("usage") or data.get("quota") or data
    if not any(isinstance(usage.get(a), dict)
               for w in OPENCODE_WINDOWS for a in OPENCODE_WINDOW_ALIASES[w]):
        result["error_code"] = "bad_response"
        result["error_message"] = "no usage windows in response"
        return result
    result["online"] = True
    worst = 0.0
    for window in OPENCODE_WINDOWS:
        win = {}
        for alias in OPENCODE_WINDOW_ALIASES[window]:
            if isinstance(usage.get(alias), dict):
                win = usage[alias]
                break
        pct = win.get("percent")
        if not isinstance(pct, (int, float)):
            pct = None
        status = win.get("status")
        result[f"{window}_percent"] = round(pct, 1) if pct is not None else None
        result[f"{window}_status"] = status
        result[f"{window}_resets_at"] = win.get("resetsAt") or win.get("resets_at")
        if pct is not None:
            worst = max(worst, pct)
        if status and status != "ok":
            result["level"] = "warn"
    if worst:
        result["worst_percent"] = round(worst, 1)
        if worst >= 100:
            result["level"] = "bad"
        elif worst >= QUOTA_WARN_PERCENT and result["level"] == "ok":
            result["level"] = "warn"
    return result


# Service check dispatcher
_CHECK_MAP = {
    "port": lambda cfg: check_port(cfg["host"], cfg["port"]),
    "maa": lambda cfg: check_maa(cfg["process_name"], cfg["log_dir"], cfg["log_glob"]),
    "maa_alerts": lambda cfg: check_maa_alerts(cfg["log_dir"], cfg["log_glob"]),
    "process": lambda cfg: check_process(cfg["process_name"], cfg.get("cmdline_match")),
    "happy": lambda cfg: check_happy(cfg.get("home_dir")),
    "maaend": lambda cfg: check_maaend(cfg["process_name"], cfg["log_dir"], cfg["log_glob"]),
    "adguard": lambda cfg: check_adguard(cfg["api_url"]),
    "syncthing": lambda cfg: check_syncthing(cfg["api_url"]),
    "utorrent": lambda cfg: check_utorrent(cfg["api_url"]),
    "webdav": lambda cfg: check_webdav(cfg["url"]),
    "deepseek": lambda cfg: check_deepseek(cfg.get("low_balance")),
    "opencode": lambda cfg: check_opencode(),
}


def run_service_checks(services_cfg: dict) -> dict:
    results: dict[str, dict] = {}
    for svc_name, svc_cfg in services_cfg.items():
        svc_type = svc_cfg.get("type")
        check_fn = _CHECK_MAP.get(svc_type) if svc_type else None
        if check_fn:
            try:
                results[svc_name] = {"type": svc_type, **check_fn(svc_cfg)}
            except Exception:
                results[svc_name] = {"type": svc_type, "online": False}
        else:
            results[svc_name] = {"type": svc_type, "online": False, "error": f"unknown type: {svc_type}"}
    return results


# ---------------------------------------------------------------------------
# Access control — source-address allowlist
# ---------------------------------------------------------------------------
# The agent has no authentication: whatever can reach the port can read every
# metric and rewrite config.json. So the port itself is restricted by source
# address, and the default below is loopback only — out of the box it answers
# nobody but the machine it runs on. Widen it with MONITOR_ALLOW_NETS when a
# dashboard on another host has to poll it.
#
# The TCP peer address is what gets checked. X-Forwarded-For and X-Real-IP are
# ordinary request headers that any client can set, so they never enter this
# decision (and there is no reverse proxy here to make them meaningful).

DEFAULT_ALLOWED_NETWORKS = (
    "127.0.0.1/32",      # loopback — local dashboard, curl, /launch/chat
    "::1/128",           # loopback, IPv6 (inert while the server is AF_INET)
)


def parse_networks(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            # strict=False so a host address with a prefix ("10.0.0.5/24")
            # means the subnet it sits in, instead of raising.
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            print(f"[monitor] ignoring unparsable network: {item!r}")
    return tuple(nets)


# Overridable via MONITOR_ALLOW_NETS (comma-separated CIDRs). Deliberately NOT
# read from config.json: POST /config replaces that file wholesale, so any
# setting kept there is silently wiped the first time the dashboard saves.
_allowed_networks = parse_networks(",".join(DEFAULT_ALLOWED_NETWORKS))


def client_allowed(client_ip: str) -> bool:
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(ip in net for net in _allowed_networks)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class MonitorHandler(BaseHTTPRequestHandler):
    device: str = "main"
    port: int = 9090
    # Stalled clients must never block a handler thread forever — otherwise a
    # single trickling request can wedge the whole monitoring agent.
    timeout = 20

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _client_ip(self) -> str:
        return (self.client_address or ("", 0))[0]

    def _check_access(self) -> bool:
        client_ip = self._client_ip()
        if client_allowed(client_ip):
            return True
        print(f"[monitor] refused {self.command} {self.path} from {client_ip}", flush=True)
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"Forbidden")
        self.close_connection = True
        return False

    def _require_json(self) -> bool:
        """Every POST must declare application/json, body or not.

        Content-Type: application/json is not CORS-safelisted, so a browser
        preflights the request before sending it instead of firing it blind at
        the agent — which is the hook a future token check would ride on.
        """
        ctype = self.headers.get("Content-Type", "")
        if ctype.split(";", 1)[0].strip().lower() == "application/json":
            return True
        print(f"[monitor] refused {self.command} {self.path} from {self._client_ip()}"
              f": Content-Type={ctype!r}", flush=True)
        self.send_response(415)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"Unsupported Media Type")
        self.close_connection = True
        return False

    def do_OPTIONS(self):
        if not self._check_access():
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if not self._check_access():
            return
        if self.path == "/":
            self._serve_json(build_response(self.device))
        elif self.path == "/config":
            self._serve_json(_active_config)
        elif self.path.startswith("/ping"):
            host = self.path.split("?host=", 1)[-1] if "?host=" in self.path else ""
            self._serve_json(do_ping(host)) if host else (self.send_response(400), self.end_headers())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if not self._check_access():
            return
        if not self._require_json():
            return
        if self.path == "/config":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = self.rfile.read(length)
                new_cfg = json.loads(body)
                if "services" not in new_cfg:
                    new_cfg["services"] = {}
                save_config(new_cfg)
                reload_config()
                self._serve_json({"ok": True, "services": list(new_cfg.get("services", {}).keys())})
            except (json.JSONDecodeError, ValueError) as e:
                self.send_response(400)
                self._cors()
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        elif self.path == "/launch/chat":
            length = int(self.headers.get("Content-Length", 0))
            action = "start"
            try:
                if length > 0:
                    action = json.loads(self.rfile.read(length)).get("action", "start")
            except (json.JSONDecodeError, ValueError):
                pass
            self._serve_json(self._launch_chat(action))
        elif self.path == "/alerts/clear":
            self._serve_json(clear_alerts())
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()

    def _launch_chat(self, action: str) -> dict:
        """Lifecycle manager for the local chat backend (12358).

        Only the local agent acts as broker (localhost-only), and only when
        chat_backend.py sits beside this file. The chat backend stays dead
        until asked — the console's expand triggers "start"; "stop" exists so
        tests can shut the elevated child down without shell elevation.
        """
        if self._client_ip() not in ("127.0.0.1", "::1"):
            return {"ok": False, "error": "forbidden"}
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_backend.py")
        if not os.path.exists(script):
            return {"ok": False, "error": "no chat backend here"}
        if action == "stop":
            pid = None
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == psutil.CONN_LISTEN and conn.laddr.port == 12358:
                    pid = conn.pid
                    break
            if pid is None:
                return {"ok": True, "already": False}
            try:
                psutil.Process(pid).kill()
                return {"ok": True, "stopped": pid}
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                return {"ok": False, "error": f"stop failed: {e}"}
        try:
            with socket.create_connection(("127.0.0.1", 12358), timeout=0.5):
                return {"ok": True, "already": True}
        except OSError:
            pass
        subprocess.Popen(
            [sys.executable, script],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            creationflags=CREATE_NO_WINDOW,
        )
        return {"ok": True, "already": False}

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode())

    def log_message(self, format, *args):
        pass  # suppress stderr logging (required for pythonw.exe)


def do_ping(host: str) -> dict:
    """ARP for LAN, ICMP for remote. ARP miss on LAN = offline."""
    try:
        ip = ipaddress.ip_address(host)
        is_private = ip.is_private
    except ValueError:
        is_private = True

    # Same-subnet IPv4 — try ARP first (immune to router ICMP spoofing)
    if is_private and isinstance(ip, ipaddress.IPv4Address):
        try:
            r = subprocess.run(
                ["arp", "-a", host],
                capture_output=True, timeout=1, creationflags=CREATE_NO_WINDOW,
            )
            out = r.stdout.decode("gbk", errors="replace")
            has_mac = bool(re.search(
                r"[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}",
                out, re.IGNORECASE))
            if has_mac:
                return {"online": True}
            # ARP miss on private subnet = genuinely offline
            return {"online": False}
        except Exception:
            pass

    # Public / non-ARP subnet — use ICMP ping
    try:
        r = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", host],
            capture_output=True, timeout=2, creationflags=CREATE_NO_WINDOW,
        )
        out = r.stdout.decode("gbk", errors="replace")
        return {"online": "TTL=" in out or "ttl=" in out}
    except Exception:
        return {"online": False}


def safe_call(fn):
    try:
        return fn()
    except Exception:
        return None


def build_response(device_id: str) -> dict:
    now = time.time()
    system = {
        "cpu": safe_call(get_cpu),
        "memory": safe_call(get_memory),
        "disks": safe_call(get_disks),
        "network": safe_call(get_network),
        "temperatures": safe_call(get_temperatures),
        "gpu": safe_call(get_gpu_usage),
    }
    services_cfg = _active_config.get("services", {})
    services = safe_call(lambda: run_service_checks(services_cfg))

    return {
        "device": device_id,
        "hostname": socket.gethostname(),
        "platform": sys.platform,
        "timestamp": round(now, 3),
        "uptime_seconds": int(now - psutil.boot_time()),
        "system": system,
        "services": services if services is not None else {},
    }


def main():
    global _allowed_networks

    parser = argparse.ArgumentParser(description="Device monitoring agent")
    parser.add_argument("--device", default=None, help="Device identity label (default: from hostname)")
    parser.add_argument("--port", type=int, default=9090, help="HTTP listen port (default: 9090)")
    args = parser.parse_args()

    env_nets = os.environ.get("MONITOR_ALLOW_NETS")
    if env_nets is not None:
        _allowed_networks = parse_networks(env_nets)  # empty spec = refuse everything

    device_id = resolve_device(args.device)
    reload_config()

    MonitorHandler.device = device_id
    MonitorHandler.port = args.port

    svc_count = len(_active_config.get("services", {}))
    server = HTTPServer(("0.0.0.0", args.port), MonitorHandler)
    print(f"[monitor] device={device_id}  services={svc_count}  listening on 0.0.0.0:{args.port}")
    nets = ", ".join(str(n) for n in _allowed_networks) or "NONE — every request will be refused"
    print(f"[monitor] accepting only source IPs in: {nets}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[monitor] shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
