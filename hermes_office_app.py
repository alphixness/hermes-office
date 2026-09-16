#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hermes 办公室 · 独立应用窗口（不是浏览器标签页）

一个进程搞定三件事：
  1) 后台线程起只读数据服务（默认 8123，被占用会自动让路）
  2) 用 pywebview 开一个**原生窗口**（Windows 走 Edge WebView2 内核，但**没有浏览器界面**：
     无地址栏、无标签页、无菜单），窗口标题就是「Hermes 办公室」
  3) 关掉窗口 = 整个程序退出，服务一起停

运行（推荐用 uv 自动拉依赖，本机无需 pip 安装任何东西）：
    uv run --with pywebview --with pythonnet python hermes_office_app.py
自检（开窗 3 秒自动关，用于确认环境没问题）：
    uv run --with pywebview --with pythonnet python hermes_office_app.py --selftest
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# ⚠️ pythonw.exe（无控制台）下 sys.stdout / sys.stderr 为 None，
#    任何 print() 都会抛 AttributeError 并打断后续代码（表现为"进程活着但没有窗口"）。
#    所以这里先把输出重定向到日志文件，保证无控制台启动也稳。
if sys.stdout is None or sys.stderr is None:
    try:
        _log = open(HERE / 'office.log', 'a', encoding='utf-8', buffering=1)
    except Exception:
        import io
        _log = io.StringIO()
    sys.stdout = sys.stderr = _log
    print('\n=== 启动 %s ===' % time.strftime('%Y-%m-%d %H:%M:%S'))

WINDOW_TITLE = 'Hermes 办公室'


def _make_dpi_aware() -> None:
    """⚠️ Windows 关键一步：Python 默认是 DPI 不感知的，
    150% 缩放下 WebView 只会拿到约 960 CSS 宽度再被放大 1.5 倍 —— 表现就是
    "右侧面板被挤出屏幕 / 什么都要滚动 / 字特别大"。声明感知后视口 = 物理像素，布局才正常。
    """
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def free_port(preferred: int = 8123) -> int:
    for p in (preferred, 8124, 8125, 9000, 9010):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', p))
                return p
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def serve(port: int, days: int) -> None:
    import office_server as srv
    srv.HERMES_HOME = srv.default_hermes_home()
    srv.WINDOW_DAYS = days
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(('127.0.0.1', port), srv.Handler)
    print(f'[服务] 数据接口 → http://127.0.0.1:{port}/api/office')
    httpd.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8123)
    ap.add_argument('--days', type=int, default=7, help='Token 统计窗口（0=今天）')
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--height', type=int, default=900)
    ap.add_argument('--selftest', action='store_true', help='开窗 3 秒自动关，用于验证环境')
    args = ap.parse_args()

    _make_dpi_aware()          # ⚠️ 必须在创建窗口之前：否则 150% 缩放下视口被压成 ~960 CSS 宽
    port = free_port(args.port)
    threading.Thread(target=serve, args=(port, args.days), daemon=True).start()
    time.sleep(1.2)   # 等服务起来

    try:
        import webview
    except ImportError:
        print('缺少 pywebview。请用：uv run --with pywebview --with pythonnet python hermes_office_app.py')
        input('按回车退出…')
        return 1

    url = f'http://127.0.0.1:{port}/'
    window = webview.create_window(
        WINDOW_TITLE, url,
        width=args.width, height=args.height,
        min_size=(1024, 680),
        background_color='#0f1117',
        text_select=False,
    )
    if args.selftest:
        def closer():
            time.sleep(3)
            try:
                window.destroy()
            except Exception:
                pass
        threading.Thread(target=closer, daemon=True).start()

    print(f'[窗口] {WINDOW_TITLE} 已打开 → {url}')
    webview.start()          # 阻塞直到窗口关闭
    print('[窗口] 已关闭，程序退出。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
