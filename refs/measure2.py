"""拆解卡片高度构成，对比阵营主题与原主题。"""
import subprocess, re, tempfile
from pathlib import Path

PROBE = """<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    function h(el){ return el ? Math.round(el.getBoundingClientRect().height) : 0; }
    function cs(el, p){ return el ? parseFloat(getComputedStyle(el)[p]) : 0; }
    var out = [];
    var card = document.querySelector('#grid .card');
    if (!card) { document.title = 'H|none'; return; }
    var head = card.querySelector('.card-header');
    var body = card.querySelector('.card-body');
    var foot = card.querySelector('.node-footer');
    var row  = card.querySelector('.metric-row');
    var st   = card.querySelector('.section-title');
    out.push('card=' + h(card));
    out.push('head=' + h(head));
    out.push('body=' + h(body));
    out.push('foot=' + h(foot));
    out.push('row=' + h(row));
    out.push('section=' + h(st));
    out.push('bodyPad=' + cs(body,'paddingTop') + '+' + cs(body,'paddingBottom'));
    out.push('headMin=' + (head?getComputedStyle(head).minHeight:'-'));
    document.title = 'H|' + out.join(' ');
  }, 900);
});
</script></head>"""

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
for label in ['orig', 'rhodes', 'endfield']:
    src = Path(f'refs/mock-{label}.html')
    if not src.exists(): continue
    tmp = Path(tempfile.gettempdir()) / f'm2-{label}.html'
    tmp.write_text(src.read_text(encoding='utf-8').replace('</head>', PROBE, 1), encoding='utf-8')
    r = subprocess.run([EDGE,'--headless','--disable-gpu','--virtual-time-budget=4000',
                        '--window-size=1440,1000','--dump-dom', tmp.as_uri()],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    m = re.search(r'<title>H\|([^<]*)</title>', r.stdout)
    print(f'{label:9s} {m.group(1) if m else "NO DATA"}')
