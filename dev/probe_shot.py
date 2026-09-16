# -*- coding: utf-8 -*-
"""开一个「装得下屏幕」的同款窗口 → 载入页面 → 置顶 → 截窗口自身区域
用法: python dev/probe_shot.py [宽] [高]   默认 1600x900（物理约 2400x1350，稳过 2560x1440）
"""
import sys, threading, time, ctypes, ctypes.wintypes as wt
sys.path.insert(0, '.')
import office_server as srv
from http.server import ThreadingHTTPServer
import webview

W = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
H = int(sys.argv[2]) if len(sys.argv) > 2 else 900
OUT = sys.argv[3] if len(sys.argv) > 3 else 'office_live.png'

u = ctypes.windll.user32
u.FindWindowW.restype = wt.HWND
u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
SWP = 0x0001 | 0x0040   # NOSIZE|SHOWWINDOW：允许移动，位置才生效

httpd = ThreadingHTTPServer(('127.0.0.1', 8131), srv.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
w = webview.create_window('office-capture', f'http://127.0.0.1:8131/', width=W, height=H)

def later():
    time.sleep(8)
    try:
        try: w.evaluate_js("document.getElementById('mask').classList.remove('on')")
        except Exception: pass
        h = u.FindWindowW(None, 'office-capture')
        u.ShowWindow(h, 9)
        u.SetWindowPos(h, -1, 0, 0, 0, 0, SWP)          # 顶层 + 移到 (10,10)，尺寸不变
        time.sleep(2.0)
        r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
        u.SetWindowPos(h, -2, 0, 0, 0, 0, SWP)
        img.save(OUT)
        print(f'SHOT ok rect=({r.left},{r.top},{r.right},{r.bottom}) size={img.size} -> {OUT}', flush=True)
    except Exception as e:
        print('SHOT fail', type(e).__name__, e, flush=True)
    w.destroy()

threading.Thread(target=later, daemon=True).start()
webview.start()
