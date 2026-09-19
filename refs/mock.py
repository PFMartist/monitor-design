#!/usr/bin/env python3
"""Render either dashboard with stubbed agent data, so the card layout can be
checked without a device online.

Each stubbed device deliberately reports a DIFFERENT amount of content — disk
count, service count, presence of GPU/temperature readings — because equal
content hides height differences that unequal content exposes.

Writes refs/mock-<theme>.html. Usage:  python refs/mock.py
"""
from pathlib import Path
import json

# (cpu, mem, disks, services, has_gpu)
PROFILES = [
    dict(cpu=32, mem=41, disks=["C:", "D:"], svc=4, gpu=True),      # 中等
    dict(cpu=67, mem=58, disks=["C:"],      svc=2, gpu=False),      # 最短
    dict(cpu=88, mem=79, disks=["C:", "D:", "E:"], svc=6, gpu=True),  # 最长
]

SERVICES = [
    ("maa", '{"online":true,"type":"maa","last_task_status":"running","last_task_name":"剿灭作战","last_task_time_iso":"2026-09-19T00:12:00"}'),
    ("syncthing", '{"online":true,"type":"syncthing","pending_files":3,"connected_devices":5}'),
    ("adguard", '{"online":true,"type":"adguard","queries_total":184000,"blocked_total":12300,"avg_processing_time_ms":14}'),
    ("webdav", '{"online":true,"type":"webdav","status_code":200,"response_time_ms":23}'),
    ("utorrent", '{"online":true,"type":"utorrent","download_speed_bytes":4200000,"upload_speed_bytes":310000,"active_count":2}'),
    ("happy", '{"online":true,"type":"happy","pid":8821,"version":"1.4.2"}'),
]

MOCK = """<script>
try {
  localStorage.setItem("monitor_pings", JSON.stringify([
    {name:"Router", host:"10.0.0.1"}, {name:"NAS", host:"10.0.0.9"},
    {name:"Printer", host:"10.0.0.20"}]));
} catch(e) {}
(function(){
  var t0 = Math.floor(Date.now()/1000);
  var P = __PROFILES__;
  var S = __SERVICES__;
  function payload(i){
    var p = P[i % P.length];
    var disks = p.disks.map(function(m, k){
      return {mount: m + "\\\\", percent: [54,72,91,38][k % 4]};
    });
    var services = {};
    for (var k = 0; k < p.svc; k++) {
      services[S[k][0]] = JSON.parse(S[k][1]);
    }
    var temps = {cpu: [44,58,71][i % 3]};
    if (p.gpu) temps.gpu = [52,64,79][i % 3];
    return {
      timestamp: t0, uptime_seconds: 86400*3 + 3600*i + 137,
      system: {
        cpu: {cpu_percent: p.cpu},
        memory: {memory_percent: p.mem},
        disks: disks,
        network: {network_bytes_recv: 1000000*(i+1), network_bytes_sent: 500000*(i+1)},
        temperatures: temps,
        gpu: p.gpu ? {gpu_percent: [18,55,83][i % 3], gpu_memory_bytes: 4294967296} : {}
      },
      services: Object.assign({
        "DeepSeek": {online:true, type:"deepseek", balance:23.41, currency:"CNY", is_available:true},
        "opencode": {online:true, type:"opencode", rolling_percent:38, weekly_percent:52, monthly_percent:41, worst_percent:52}
      }, services)
    };
  }
  var n = 0;
  window.fetch = function(){
    return Promise.resolve({ok:true, json:function(){return Promise.resolve(payload(n++));}});
  };
})();
</script>
</head>"""


def main() -> int:
    body = (MOCK
            .replace("__PROFILES__", json.dumps(PROFILES))
            .replace("__SERVICES__", json.dumps(SERVICES)))
    root_uri = Path.cwd().as_uri() + "/"
    # dashboard.html 是单文件，默认主题 endfield；再生成一个强制 crt 的变体
    src = Path("dashboard.html").read_text(encoding="utf-8")
    root_uri = Path.cwd().as_uri() + "/"
    for label, theme in [("default", None), ("crt", "crt")]:
        out = src.replace("</head>", body, 1)
        if theme:
            out = (out.replace('data-default-theme="endfield"', f'data-default-theme="{theme}"')
                      .replace('data-theme="endfield"', f'data-theme="{theme}"', 1))
        # mock 落在 refs/ 下，相对路径 assets/... 会指错，改绝对 file://
        out = out.replace('url("assets/', f'url("{root_uri}assets/')
        Path(f"refs/mock-{label}.html").write_text(out, encoding="utf-8")
        print(f"wrote refs/mock-{label}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
