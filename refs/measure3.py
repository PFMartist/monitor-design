"""列出卡片每个直接子元素的盒模型，找出高度到底花在哪。"""
import subprocess, re, tempfile
from pathlib import Path

PROBE = """<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    var c = document.querySelector('#grid .card');
    if (!c) { document.title='H|none'; return; }
    var o = [];
    o.push('CARD h=' + c.getBoundingClientRect().height.toFixed(1)
         + ' pad=' + getComputedStyle(c).paddingTop + '/' + getComputedStyle(c).paddingBottom
         + ' bord=' + getComputedStyle(c).borderTopWidth + '/' + getComputedStyle(c).borderBottomWidth
         + ' rowGap=' + getComputedStyle(c).rowGap);
    for (var i=0;i<c.children.length;i++){
      var k=c.children[i], s=getComputedStyle(k);
      var r=k.getBoundingClientRect();
      o.push(k.className + ' h=' + r.height.toFixed(1)
           + ' m=' + s.marginTop + '/' + s.marginBottom
           + ' p=' + s.paddingTop + '/' + s.paddingBottom
           + (s.display==='none' ? ' HIDDEN' : ''));
    }
    document.title = 'H|' + o.join(' || ');
  }, 900);
});
</script></head>"""

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
for label in ['orig', 'rhodes']:
    src = Path(f'refs/mock-{label}.html')
    tmp = Path(tempfile.gettempdir()) / f'm3-{label}.html'
    tmp.write_text(src.read_text(encoding='utf-8').replace('</head>', PROBE, 1), encoding='utf-8')
    r = subprocess.run([EDGE,'--headless','--disable-gpu','--virtual-time-budget=4000',
                        '--window-size=1440,1000','--dump-dom', tmp.as_uri()],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    m = re.search(r'<title>H\|([^<]*)</title>', r.stdout)
    print(f'=== {label} ===')
    for part in (m.group(1) if m else 'NO DATA').split(' || '):
        print('  ', part)
