# -*- coding: utf-8 -*-
"""测量真实 CSS 视口 + 各处 rect（按传入窗口尺寸；默认与应用同尺寸 1721x1033）"""
import sys, threading, time, json
sys.path.insert(0, '.')
import office_server as srv
from http.server import ThreadingHTTPServer
import webview
W = int(sys.argv[1]) if len(sys.argv) > 1 else 1721
H = int(sys.argv[2]) if len(sys.argv) > 2 else 1033
httpd = ThreadingHTTPServer(('127.0.0.1', 8131), srv.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
w = webview.create_window('probe', 'http://127.0.0.1:8131/', width=W, height=H)
JS = """(() => {
  const R = e => { if(!e) return null; const b = e.getBoundingClientRect();
    return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)]; };
  const desks = [...document.querySelectorAll('#staff .desk')];
  const rows = {};
  desks.forEach(d => { const y = Math.round(d.getBoundingClientRect().top); rows[y] = (rows[y]||0)+1; });
  const av = document.querySelector('#staff .desk .avatar');
  const avW = av ? Math.round(av.getBoundingClientRect().width) : 0;
  const maxBottom = desks.length ? Math.max(...desks.map(d => d.getBoundingClientRect().bottom)) : 0;
  return JSON.stringify({
    viewport:[innerWidth, innerHeight], dpr:devicePixelRatio,
    aside:R(document.querySelector('aside')),
    asideVisible: document.querySelector('aside').getBoundingClientRect().right <= innerWidth + 1,
    staff:R(document.querySelector('#staff')),
    deskCount:desks.length, rows, avatarCss:avW,
    maxBottom:Math.round(maxBottom), fitsH: maxBottom <= innerHeight,
    needScroll: document.documentElement.scrollHeight > innerHeight + 1
  });
})()"""
def later():
    time.sleep(7)
    print('MEASURE ' + str(w.evaluate_js(JS)), flush=True)
    w.destroy()
threading.Thread(target=later, daemon=True).start()
webview.start()
