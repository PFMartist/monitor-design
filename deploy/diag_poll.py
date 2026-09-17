#!/usr/bin/env python3
"""Diagnostic poller: requests the agent at fixed intervals and logs results."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# urllib consults the Windows proxy settings on every request, and CPython's
# bypass check (urllib.request.proxy_bypass_registry) calls socket.getfqdn() —
# a reverse DNS lookup — before the request even goes out. Loopback answers
# instantly from the hosts file; anything else waits out the resolver — on the
# order of seconds per request. An empty ProxyHandler skips that check entirely.
#
# Worth remembering when reading latency numbers from this tool: before this
# fix it was measuring its own proxy bypass as if it were network time.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def poll(url: str, timeout: float) -> dict:
    t0 = time.perf_counter()
    try:
        with _NO_PROXY_OPENER.open(url, timeout=timeout) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            body = json.loads(resp.read())
            return {
                "ts": time.strftime("%H:%M:%S"),
                "ok": True,
                "status": resp.status,
                "elapsed_ms": elapsed,
                "agent_device": body.get("device"),
                "agent_ts": body.get("timestamp"),
            }
    except urllib.error.HTTPError as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return {"ts": time.strftime("%H:%M:%S"), "ok": False, "status": e.code, "elapsed_ms": elapsed, "error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return {"ts": time.strftime("%H:%M:%S"), "ok": False, "status": 0, "elapsed_ms": elapsed, "error": str(e.reason)}
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        return {"ts": time.strftime("%H:%M:%S"), "ok": False, "status": 0, "elapsed_ms": elapsed, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Diagnostic agent poller")
    parser.add_argument("--url", default="http://localhost:9090/", help="Agent URL")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--timeout", type=float, default=3.0, help="Request timeout in seconds")
    parser.add_argument("--count", type=int, default=60, help="Number of polls (0 = infinite)")
    parser.add_argument("--json", action="store_true", help="Output as JSON lines")
    args = parser.parse_args()

    if args.json:
        fmt = "json"
    else:
        print(f"Polling {args.url} every {args.interval}s  timeout={args.timeout}s  count={'∞' if args.count==0 else args.count}")
        print(f"{'TIME':>8}  {'OK':5}  {'MS':>6}  DETAIL")
        print("-" * 50)
        fmt = "text"

    success = 0
    fail = 0
    times: list[float] = []
    i = 0
    while args.count == 0 or i < args.count:
        result = poll(args.url, args.timeout)
        if result["ok"]:
            success += 1
        else:
            fail += 1
        times.append(result["elapsed_ms"])

        if fmt == "json":
            print(json.dumps(result))
        else:
            detail = ""
            if result["ok"]:
                detail = f"device={result.get('agent_device','?')}  server_ts={result.get('agent_ts','?')}"
            else:
                detail = result.get("error", "?")
            marker = "  OK" if result["ok"] else "FAIL"
            print(f"{result['ts']:>8}  {marker:5}  {result['elapsed_ms']:>5}ms  {detail}")

        i += 1
        if args.count == 0 or i < args.count:
            time.sleep(args.interval)

    # Summary
    total = success + fail
    if fmt == "text" and total > 0:
        avg = sum(times) / len(times)
        print("-" * 50)
        print(f"Total: {total}  OK: {success}  FAIL: {fail}  "
              f"Rate: {success*100/total:.1f}%  "
              f"Avg: {avg:.0f}ms  Min: {min(times):.0f}ms  Max: {max(times):.0f}ms")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
