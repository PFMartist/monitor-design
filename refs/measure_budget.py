"""900px 视口、chat 展开时，纵向空间被谁占了。"""
import subprocess, re, tempfile
from pathlib import Path
PROBE = """<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    document.documentElement.dataset.theme='__THEME__';
    if (window.chatToggle) window.chatToggle(true);
    setTimeout(function(){
      function h(sel){ var e=document.querySelector(sel);
        return e ? Math.round(e.getBoundingClientRect().height) : 0; }
      function m(sel,prop){ var e=document.querySelector(sel);
        return e ? Math.round(parseFloat(getComputedStyle(e)[prop])||0) : 0; }
      document.title='H|' + [
        'vh=' + window.innerHeight,
        'header=' + h('#header'),
        'opsStrip=' + h('#ops-strip') + '+m' + (m('#ops-strip','marginTop')+m('#ops-strip','marginBottom')),
        'grid=' + h('#grid'),
        'bottomRow=' + h('#bottom-row'),
        'viewFooter=' + h('#view-footer'),
        'console=' + h('#console-dock'),
        'dockInfo=' + h('#dock-info')
      ].join(' ');
    }, 600);
  }, 600);
});
</script></head>"""
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
src = Path('refs/mock-endfield.html').read_text(encoding='utf-8')
for theme in ['crt','rhodes','endfield']:
    tmp = Path(tempfile.gettempdir())/f'mb-{theme}.html'
    tmp.write_text(src.replace('</head>', PROBE.replace('__THEME__',theme),1), encoding='utf-8')
    r = subprocess.run([EDGE,'--headless','--disable-gpu','--virtual-time-budget=5000',
        '--window-size=720,1232','--dump-dom', tmp.as_uri()],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    m = re.search(r'<title>H\|([^<]*)</title>', r.stdout)
    print(f'{theme:9s} {m.group(1) if m else "NONE"}')
