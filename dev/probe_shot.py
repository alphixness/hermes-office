# -*- coding: utf-8 -*-
"""开一个与办公室同尺寸的窗口 → 载入页面 → 置前 → 截图（自己进程可置前，比 PrintWindow 可靠）"""
import sys, threading, time, ctypes, ctypes.wintypes as wt
sys.path.insert(0, '.')
import office_server as srv
from http.server import ThreadingHTTPServer
import webview
W, H = 1721, 1033
httpd = ThreadingHTTPServer(('127.0.0.1', 8131), srv.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
u = ctypes.windll.user32
w = webview.create_window('probe-shot', 'http://127.0.0.1:8131/', width=W, height=H)
def later():
    time.sleep(8)
    try:
        u.FindWindowW.restype = wt.HWND
        h = u.FindWindowW(None, 'probe-shot')
        u.ShowWindow(h, 9); u.SetForegroundWindow(h); u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0002|0x0001|0x0040)
        try: w.evaluate_js("document.getElementById('mask').classList.remove('on')")
        except Exception: pass
        time.sleep(2.0)
        r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save('office_live.png')
        u.SetWindowPos(h, -2, 0, 0, 0, 0, 0x0002|0x0001)
        print('SHOT ok', r.left, r.top, r.right-r.left, r.bottom-r.top, flush=True)
    except Exception as e:
        print('SHOT fail', e, flush=True)
    w.destroy()
threading.Thread(target=later, daemon=True).start()
webview.start()
