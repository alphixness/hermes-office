#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给"员工"批量生成唯美卡通头像（走 Agnes 图像 API，零第三方依赖）

用法：
    python make_avatars.py              # 只补缺失的（已有头像跳过）
    python make_avatars.py --only coder # 只出一张（先看风格，满意再铺开）
    python make_avatars.py --force      # 全部重出

产物：avatars/<id>.png（1:1，约 1024~2048 像素）
配置：agents.json（改 name/role/prompt/STYLE 即可调整人设与画风）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'avatars'
API = 'https://api.agnes-ai.cn/v1/images/generations'
MODEL = 'agnes-image-2.5-flash'
NEG = ('no text, no letters, no words, no watermark, no signature, no logo, '
       'no frame, no border, no chinese characters')


def load_key() -> str:
    """从 Hermes 的 .env 读 AGNES_API_KEY（也支持环境变量）"""
    k = os.environ.get('AGNES_API_KEY')
    if k:
        return k.strip()
    for home in (os.environ.get('HERMES_HOME'),
                 str(Path.home() / '.hermes'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'hermes')):
        if not home:
            continue
        env = Path(home) / '.env'
        if env.exists():
            for line in env.read_text(encoding='utf-8', errors='ignore').splitlines():
                if line.strip().startswith('AGNES_API_KEY'):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise SystemExit('未找到 AGNES_API_KEY（请在环境变量或 ~/.hermes/.env 中配置）')


def gen(prompt: str, key: str, retries: int = 4) -> bytes:
    body = json.dumps({
        'model': MODEL, 'prompt': prompt, 'n': 1, 'size': '1024x1024',
        'response_format': 'url',
    }).encode('utf-8')
    last = None
    for i in range(retries):
        req = urllib.request.Request(API, data=body, headers={
            'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode('utf-8'))
            item = (data.get('data') or [{}])[0]
            url = item.get('url') or item.get('b64_json')
            if not url:
                raise RuntimeError(f'返回里没有图片: {str(data)[:200]}')
            if url.startswith('http'):
                with urllib.request.urlopen(url, timeout=180) as ir:
                    return ir.read()
            import base64
            return base64.b64decode(url)
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.read().decode("utf-8", "ignore")[:160]}'
        except Exception as e:
            last = f'{type(e).__name__}: {e}'
        time.sleep(2 * (i + 1))
    raise RuntimeError(last or 'unknown error')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='只出指定 id')
    ap.add_argument('--force', action='store_true', help='已存在也重出')
    args = ap.parse_args()

    cfg = json.loads((HERE / 'agents.json').read_text(encoding='utf-8'))
    style = cfg.get('STYLE', '')
    agents = cfg['agents']
    if args.only:
        agents = [a for a in agents if a['id'] == args.only]
        if not agents:
            raise SystemExit(f'配置里没有 id={args.only}')

    key = load_key()
    OUT.mkdir(exist_ok=True)
    ok = 0
    for a in agents:
        dst = OUT / f"{a['id']}.png"
        if dst.exists() and not args.force:
            print(f'  ⏭  {a["id"]:<16} 已存在，跳过')
            continue
        prompt = f"{a['prompt']}. {style}. {NEG}"
        t0 = time.time()
        print(f'  🎨 {a["id"]:<16} 生成中…（{a.get("name")} / {a.get("role")}）', flush=True)
        try:
            data = gen(prompt, key)
            dst.write_bytes(data)
            ok += 1
            print(f'     ✅ {dst.name}  {len(data)/1024:.0f} KB  {time.time()-t0:.1f}s')
        except Exception as e:
            print(f'     ❌ 失败：{e}')
    print(f'\n完成：{ok}/{len(agents)} 张 → {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
