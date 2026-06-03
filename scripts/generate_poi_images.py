#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Pillow 为每个 POI 生成精美的本地封面图
速度极快（100张 < 3秒），零网络依赖
"""

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# 尝试导入 Pillow
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[错误] 需要安装 Pillow: pip install Pillow")
    sys.exit(1)

# 路径配置
PROJECT_ROOT = Path(__file__).parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "杭州_pois_mock.json"
OUTPUT_DIR = PROJECT_ROOT / "frontend" / "images" / "pois"

# 分类配色方案（背景渐变起始色和结束色）
CATEGORY_COLORS = {
    "风景名胜": ("#667eea", "#764ba2"),   # 紫蓝
    "餐饮服务": ("#f093fb", "#f5576c"),   # 粉红
    "咖啡厅": ("#4facfe", "#00f2fe"),     # 青蓝
    "购物服务": ("#43e97b", "#38f9d7"),   # 翠绿
    "博物馆": ("#fa709a", "#fee140"),     # 粉黄
    "休闲娱乐": ("#30cfd0", "#330867"),   # 深青紫
    "文化": ("#a8edea", "#fed6e3"),       # 粉蓝
    "酒店宾馆": ("#ff9a9e", "#fecfef"),   # 浅粉
}

# 分类图标用几何图形替代（避免Windows字体不支持emoji）
# 每个分类定义一个绘制函数，在画布上画简单形状
def draw_icon(draw, cx, cy, size, category):
    """在指定中心位置绘制分类图标"""
    if category == "风景名胜":
        # 画山峰（三角形+山顶）
        s = size
        draw.polygon([(cx, cy-s//2), (cx-s//2, cy+s//3), (cx+s//2, cy+s//3)], fill="white")
        draw.polygon([(cx-s//4, cy+s//3), (cx-s//2, cy+s//2), (cx+s//4, cy+s//2)], fill="white")
    elif category == "餐饮服务":
        # 画碗（半圆+底座）
        r = size // 2
        draw.pieslice([cx-r, cy-r//2, cx+r, cy+r], start=0, end=180, fill="white")
        draw.rectangle([cx-r//2, cy+r//2, cx+r//2, cy+r//2+4], fill="white")
    elif category == "咖啡厅":
        # 画杯子（矩形+把手）
        w, h = size//2, size//2+6
        draw.rounded_rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], radius=4, fill="white")
        draw.arc([cx+w//2-2, cy-h//4, cx+w//2+8, cy+h//4], start=270, end=90, fill="white", width=3)
    elif category == "购物服务":
        # 画购物袋（矩形+提手）
        w, h = size//2, size//2+4
        draw.rounded_rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], radius=3, fill="white")
        draw.arc([cx-w//4, cy-h//2-8, cx+w//4, cy-h//2+2], start=0, end=180, fill="white", width=3)
    elif category == "博物馆":
        # 画柱子建筑（矩形+三角顶）
        w, h = size//2, size//3
        draw.rectangle([cx-w//2, cy-h//3, cx+w//2, cy+h], fill="white")
        draw.polygon([(cx, cy-h//2-4), (cx-w//2-4, cy-h//3), (cx+w//2+4, cy-h//3)], fill="white")
    elif category == "休闲娱乐":
        # 画星星（五角星简化版：菱形）
        s = size // 2
        draw.polygon([(cx, cy-s), (cx+s//2, cy), (cx, cy+s), (cx-s//2, cy)], fill="white")
    elif category == "文化":
        # 画书（矩形+竖线）
        w, h = size//3, size//2
        draw.rounded_rectangle([cx-w//2, cy-h//2, cx+w//2, cy+h//2], radius=2, fill="white")
        draw.line([(cx, cy-h//2+4), (cx, cy+h//2-4)], fill=CATEGORY_COLORS.get(category, ("#667eea", "#764ba2"))[0], width=2)
    elif category == "酒店宾馆":
        # 画床（横矩形+竖柱）
        w, h = size//2, size//3
        draw.rectangle([cx-w//2, cy-h//3, cx+w//2, cy+h//3], fill="white")
        draw.rectangle([cx-w//2, cy-h//3, cx-w//2+6, cy+h//3], fill="white")
    else:
        # 默认：圆形
        r = size // 2
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill="white")

IMG_WIDTH = 400
IMG_HEIGHT = 250


def get_font(size: int):
    """获取系统可用的中文字体"""
    font_paths = [
        "C:/Windows/Fonts/simhei.ttf",       # 黑体
        "C:/Windows/Fonts/simsun.ttc",       # 宋体
        "C:/Windows/Fonts/msyh.ttc",         # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",       # 微软雅黑粗体
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def draw_gradient(draw: ImageDraw.Draw, width: int, height: int, color1: str, color2: str):
    """绘制垂直渐变色背景"""
    rgb1 = hex_to_rgb(color1)
    rgb2 = hex_to_rgb(color2)
    for y in range(height):
        ratio = y / height
        r = int(rgb1[0] + (rgb2[0] - rgb1[0]) * ratio)
        g = int(rgb1[1] + (rgb2[1] - rgb1[1]) * ratio)
        b = int(rgb1[2] + (rgb2[2] - rgb1[2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def generate_poi_image(poi: dict, save_path: Path) -> bool:
    """为单个 POI 生成封面图"""
    category = poi.get("category", "其他")
    name = poi.get("name", "未知")
    city = poi.get("city", "")
    
    c1, c2 = CATEGORY_COLORS.get(category, ("#667eea", "#764ba2"))
    
    # 创建图片
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(img)
    
    # 绘制渐变背景
    draw_gradient(draw, IMG_WIDTH, IMG_HEIGHT, c1, c2)
    
    # 加载字体
    font_name = get_font(28)
    font_cat = get_font(14)
    
    # 绘制几何图标（居中偏上）
    draw_icon(draw, IMG_WIDTH // 2, 85, 50, category)
    
    # 绘制 POI 名称（居中）
    bbox = draw.textbbox((0, 0), name, font=font_name)
    name_w = bbox[2] - bbox[0]
    name_x = (IMG_WIDTH - name_w) // 2
    draw.text((name_x, 130), name, fill="white", font=font_name)
    
    # 绘制分类和城市（下方）
    sub_text = f"{category} · {city}"
    bbox = draw.textbbox((0, 0), sub_text, font=font_cat)
    sub_w = bbox[2] - bbox[0]
    sub_x = (IMG_WIDTH - sub_w) // 2
    draw.text((sub_x, 175), sub_text, fill=(220, 220, 255), font=font_cat)
    
    # 添加装饰短线
    draw.line([(IMG_WIDTH//2 - 15, 210), (IMG_WIDTH//2 + 15, 210)], fill="white", width=2)
    
    # 保存
    img.save(save_path, "JPEG", quality=90)
    return True


def main():
    print("=" * 60)
    print("POI 封面图本地生成工具 (Pillow)")
    print("=" * 60)
    
    if not DATA_FILE.exists():
        print(f"\n[错误] 数据文件不存在: {DATA_FILE}")
        sys.exit(1)
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        pois = json.load(f)
    
    print(f"\n共 {len(pois)} 个 POI")
    print(f"输出目录: {OUTPUT_DIR}")
    print()
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    success = 0
    skipped = 0
    
    for i, poi in enumerate(pois, 1):
        poi_id = poi["poi_id"]
        name = poi["name"]
        save_path = OUTPUT_DIR / f"{poi_id}.jpg"
        
        if save_path.exists():
            skipped += 1
            continue
        
        generate_poi_image(poi, save_path)
        success += 1
        
        if i % 20 == 0:
            print(f"  进度: {i}/{len(pois)}")
    
    print(f"\n生成完成: 新生成 {success} 张 | 跳过 {skipped} 张")
    print(f"保存位置: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
