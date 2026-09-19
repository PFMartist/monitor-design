"""报告每张卡片的实际渲染高度，用于对比阵营主题与原主题。"""
from pathlib import Path
import subprocess, re, tempfile, json

PROBE = """<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    var out = [];
    document.querySelectorAll('#grid .card').forEach(function(c){
      var n = c.querySelector('.device-name');
      out.push((n?n.textContent:'?') + '=' + Math.round(c.getBoundingClientRect().height));
    });
    var g = document.getElementById('grid');
    document.title = 'H|' + out.join(',') + '|grid=' + (g?Math.round(g.getBoundingClientRect().height):'?');
  }, 900);
});
</script></head>"""

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

for label in ['orig', 'rhodes', 'endfield']:
    src = Path(f'refs/mock-{label}.html')
    if not src.exists():
        print(f'{label:9s}  (no mock)'); continue
    tmp = Path(tempfile.gettempdir()) / f'm-{label}.html'
    tmp.write_text(src.read_text(encoding='utf-8').replace('</head>', PROBE, 1), encoding='utf-8')
    r = subprocess.run([EDGE, '--headless', '--disable-gpu', '--virtual-time-budget=4000',
                        '--window-size=1440,1000', '--dump-dom', tmp.as_uri()],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    m = re.search(r'<title>H\|([^<]*)</title>', r.stdout)
    print(f'{label:9s}  {m.group(1) if m else "NO DATA"}')
