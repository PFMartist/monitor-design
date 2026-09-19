"""报告底部各元素的上下边缘。"""
import subprocess, re, tempfile
from pathlib import Path
PROBE = """<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    function b(sel){
      var e=document.querySelector(sel); if(!e) return sel+'=none';
      var r=e.getBoundingClientRect(), s=getComputedStyle(e);
      return sel.replace('#','')+'[y '+Math.round(r.top)+'..'+Math.round(r.bottom)
        +' h='+Math.round(r.height)+(s.display==='none'?' HID':'')+']';
    }
    var o=[];
    ['#grid','#bottom-row','#dock-left','#console-dock','#dock-info','#faction-identity','#view-footer']
      .forEach(function(s){o.push(b(s));});
    var c=document.querySelector('#grid .card');
    if(c){var r=c.getBoundingClientRect();o.push('card[y '+Math.round(r.top)+'..'+Math.round(r.bottom)+']');}
    document.title='H|'+o.join('  ');
  },900);
});
</script></head>"""
EDGE=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
for label in ['endfield','rhodes']:
    src=Path(f'refs/mock-{label}.html')
    tmp=Path(tempfile.gettempdir())/f'mv-{label}.html'
    tmp.write_text(src.read_text(encoding='utf-8').replace('</head>',PROBE,1),encoding='utf-8')
    r=subprocess.run([EDGE,'--headless','--disable-gpu','--virtual-time-budget=4000',
        '--window-size=1440,1000','--dump-dom',tmp.as_uri()],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
    m=re.search(r'<title>H\|([^<]*)</title>',r.stdout)
    print(f'=== {label} ===')
    for p in (m.group(1) if m else 'NONE').split('  '): print('  ',p)
