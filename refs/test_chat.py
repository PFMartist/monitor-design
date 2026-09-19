"""展开/收起 chat 时卡片是否被裁切。按指定宽度逐个加载，回读实际主题校验。

用法:  python refs/test_chat.py <宽度> <高1> [高2 ...]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = """<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    document.documentElement.dataset.theme = '__THEME__';
    var wantExpand = __EXPAND__;
    if (wantExpand && window.chatToggle) window.chatToggle(true);
    setTimeout(function(){
      var g = document.getElementById('grid');
      var cards = document.querySelectorAll('#grid .card');
      var bottom = 0, rows = {};
      cards.forEach(function(c){
        bottom = Math.max(bottom, c.getBoundingClientRect().bottom);
        rows[Math.round(c.getBoundingClientRect().top)] = 1;
      });
      var gr = g.getBoundingClientRect();
      document.title = 'H|theme=' + document.documentElement.dataset.theme
        + ' inner=' + window.innerWidth + 'x' + window.innerHeight
        + ' rows=' + Object.keys(rows).length
        + ' gridH=' + Math.round(gr.height)
        + ' need=' + g.scrollHeight
        + ' clip=' + Math.max(0, Math.round(g.scrollHeight - g.clientHeight))
        + ' cardOver=' + Math.round(Math.max(0, bottom - gr.bottom));
    }, 600);
  }, 600);
});
</script></head>"""

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

W = int(sys.argv[1]) if len(sys.argv) > 1 else 1440
HEIGHTS = [int(x) for x in sys.argv[2:]] or [1080, 900, 800, 720]
src = Path('refs/mock-endfield.html').read_text(encoding='utf-8')   # 含全部 5 套主题

print(f'宽度 {W}px')
print(f'{"expand":6s} {"theme":10s} {"inner":>10s} {"rows":>4s} {"gridH":>6s} '
      f'{"need":>5s} {"clip":>5s} {"cardOver":>8s}')
for theme in ['crt', 'endfield']:
    for expand in (False, True):
        for vh in HEIGHTS:
            tmp = Path(tempfile.gettempdir()) / f'ct-{W}-{theme}-{vh}-{expand}.html'
            body = (PROBE.replace('__THEME__', theme)
                         .replace('__EXPAND__', 'true' if expand else 'false'))
            tmp.write_text(src.replace('</head>', body, 1), encoding='utf-8')
            r = subprocess.run([EDGE, '--headless', '--disable-gpu',
                                '--virtual-time-budget=5000',
                                f'--window-size={W},{vh}', '--dump-dom', tmp.as_uri()],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=120)
            m = re.search(r'<title>H\|([^<]*)</title>', r.stdout)
            d = dict(kv.split('=') for kv in m.group(1).split()) if m else {}
            flag = '' if d.get('clip') == '0' else '   <-- 裁切'
            print(f'{str(expand):6s} {d.get("theme","?"):10s} {d.get("inner","?"):>10s} '
                  f'{d.get("rows","?"):>4s} {d.get("gridH","?"):>6s} {d.get("need","?"):>5s} '
                  f'{d.get("clip","?"):>5s} {d.get("cardOver","?"):>8s}{flag}')
