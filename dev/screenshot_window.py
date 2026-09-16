# -*- coding: utf-8 -*-
"""PrintWindow(PW_RENDERFULLCONTENT) 抓窗口自身内容 —— 不受其它窗口遮挡影响"""
import ctypes, ctypes.wintypes as wt, os, sys
from pathlib import Path
from PIL import Image

TITLE = 'Hermes 办公室'
OUT = Path(__file__).resolve().parent / 'office_shot.png'
u = ctypes.windll.user32; g = ctypes.windll.gdi32
u.FindWindowW.restype = wt.HWND
h = u.FindWindowW(None, TITLE)
print('  FindWindowW =', h)
if not h: sys.exit('  ⚠️ 窗口未找到')

class BMIH(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                ('biPlanes', wt.WORD), ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wt.DWORD), ('biClrImportant', wt.DWORD)]
class BMI(ctypes.Structure):
    _fields_ = [('bmiHeader', BMIH), ('bmiColors', wt.DWORD * 3)]

r = wt.RECT(); u.GetWindowRect(h, ctypes.byref(r))
w, ht = r.right - r.left, r.bottom - r.top
hdc = u.GetWindowDC(h); mdc = g.CreateCompatibleDC(hdc)
bmp = g.CreateCompatibleBitmap(hdc, w, ht); g.SelectObject(mdc, bmp)
ok = u.PrintWindow(h, mdc, 2)                      # 2 = PW_RENDERFULLCONTENT
bi = BMI(); bi.bmiHeader.biSize = ctypes.sizeof(BMIH); bi.bmiHeader.biWidth = w
bi.bmiHeader.biHeight = -ht; bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32
buf = ctypes.create_string_buffer(w * ht * 4)
g.GetDIBits(mdc, bmp, 0, ht, buf, ctypes.byref(bi), 0)
img = Image.frombuffer('RGBA', (w, ht), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
img.save(OUT)
g.DeleteObject(bmp); g.DeleteDC(mdc); u.ReleaseDC(h, hdc)
print(f'  PrintWindow={ok}  尺寸 {w}x{ht}  截图: ✅ {os.path.getsize(OUT)/1024:.0f} KB')
