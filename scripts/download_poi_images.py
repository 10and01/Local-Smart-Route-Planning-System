#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载 POI 封面图到本地
从 Pollinations.ai 获取 AI 生成图片，保存到 frontend/images/pois/
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# 路径配置
PROJECT_ROOT = Path(__file__).parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "杭州_pois_mock.json"
OUTPUT_DIR = PROJECT_ROOT / "frontend" / "images" / "pois"

# 下载参数
TIMEOUT = 30  # 单张图片超时
RETRY = 2     # 失败重试次数
DELAY = 0.5   # 请求间隔（秒），避免并发过高


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def download_image(url: str, save_path: Path, timeout: int = TIMEOUT) -> bool:
    """下载单张图片，带重试"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0"
    }
    for attempt in range(RETRY + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) > 1000:  # 过滤掉错误页面
                        with open(save_path, "wb") as f:
                            f.write(data)
                        return True
        except Exception as e:
            if attempt < RETRY:
                time.sleep(1)
            else:
                print(f"    ✗ 下载失败: {e}")
    return False


def main():
    print("=" * 60)
    print("POI 图片批量下载工具")
    print("来源: Pollinations.ai")
    print("=" * 60)

    if not DATA_FILE.exists():
        print(f"\n[错误] 数据文件不存在: {DATA_FILE}")
        sys.exit(1)

    # 读取 POI 数据
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        pois = json.load(f)

    print(f"\n共 {len(pois)} 个 POI 待处理")
    print(f"输出目录: {OUTPUT_DIR}")
    print()

    ensure_dir(OUTPUT_DIR)

    success = 0
    failed = 0
    skipped = 0

    for i, poi in enumerate(pois, 1):
        poi_id = poi["poi_id"]
        name = poi["name"]
        photos = poi.get("photos", [])

        save_path = OUTPUT_DIR / f"{poi_id}.jpg"

        # 如果已存在则跳过
        if save_path.exists():
            print(f"[{i}/{len(pois)}] ⏭ {name} (已存在)")
            skipped += 1
            continue

        if not photos:
            print(f"[{i}/{len(pois)}] ⚠ {name} (无图片URL)")
            failed += 1
            continue

        # 取第一张图片URL
        url = photos[0]
        print(f"[{i}/{len(pois)}] ↓ {name}", end=" ", flush=True)

        ok = download_image(url, save_path)
        if ok:
            size = save_path.stat().st_size
            print(f"✓ ({size//1024}KB)")
            success += 1
        else:
            print(f"✗")
            failed += 1

        time.sleep(DELAY)

    print("\n" + "=" * 60)
    print(f"下载完成: 成功 {success} | 跳过 {skipped} | 失败 {failed}")
    print(f"图片保存在: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
