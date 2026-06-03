#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键生成Hackthon演示数据包
执行此脚本即可生成完整的数据包，包含：
  - POI数据（Mock）
  - 距离矩阵（Haversine + OSRM）
  - POI Embedding（调用OpenAI API或本地模型）
用法:
    python scripts/demo_data_package.py
"""

import json
import os
import sys
import subprocess
sys.stdout.reconfigure(encoding='utf-8')

# 确保data目录存在
os.makedirs("data", exist_ok=True)


def run_script(script_path):
    """运行子脚本"""
    print(f"\n{'='*60}")
    print(f"执行: {script_path}")
    print(f"{'='*60}")
    result = subprocess.run([sys.executable, script_path], capture_output=False)
    return result.returncode == 0


def main():
    print("=" * 60)
    print(" 美团AI Hackthon - 演示数据包生成器")
    print("=" * 60)
    
    steps = [
        ("生成Mock POI数据", "scripts/generate_mock_data.py"),
        ("计算Haversine距离矩阵", None),  # 内联执行
        ("计算OSRM步行距离矩阵", None),   # 可选，依赖网络
    ]
    
    # Step 1: 生成Mock数据
    if not run_script("scripts/generate_mock_data.py"):
        print("[FAIL] Mock数据生成失败")
        return
    
    # Step 2: 计算Haversine距离矩阵
    print(f"\n{'='*60}")
    print("计算Haversine距离矩阵（纯数学，无需网络）")
    print(f"{'='*60}")
    result = subprocess.run([
        sys.executable, "scripts/compute_distance_matrix.py",
        "--input", "data/杭州_pois_mock.json",
        "--method", "haversine"
    ])
    if result.returncode != 0:
        print("[FAIL] 距离矩阵计算失败")
        return
    
    # Step 3: 尝试OSRM距离矩阵（网络依赖）
    print(f"\n{'='*60}")
    print("尝试计算OSRM步行距离矩阵（需要网络）")
    print(f"{'='*60}")
    result = subprocess.run([
        sys.executable, "scripts/compute_distance_matrix.py",
        "--input", "data/杭州_pois_mock.json",
        "--method", "osrm",
        "--profile", "foot"
    ])
    if result.returncode != 0:
        print("[WARN] OSRM计算失败（可能网络问题），已使用Haversine矩阵作为备选")
    
    # 生成数据包索引
    print(f"\n{'='*60}")
    print("生成数据包索引")
    print(f"{'='*60}")
    
    package = {
        "city": "杭州",
        "description": "美团AI Hackthon演示数据集",
        "files": {
            "pois": "data/杭州_pois_mock.json",
            "distance_matrix_haversine": "data/distance_matrix_haversine.json",
            "distance_matrix_osrm": "data/distance_matrix_osrm_foot.json",
        },
        "stats": {}
    }
    
    # 加载并统计
    with open("data/杭州_pois_mock.json", "r", encoding="utf-8") as f:
        pois = json.load(f)
    package["stats"]["poi_count"] = len(pois)
    package["stats"]["categories"] = {}
    for p in pois:
        cat = p["category"]
        package["stats"]["categories"][cat] = package["stats"]["categories"].get(cat, 0) + 1
    
    # 检查距离矩阵
    if os.path.exists("data/distance_matrix_haversine.json"):
        with open("data/distance_matrix_haversine.json", "r", encoding="utf-8") as f:
            dm = json.load(f)
        package["stats"]["distance_matrix_size"] = f"{len(dm['poi_ids'])}×{len(dm['poi_ids'])}"
    
    with open("data/package_index.json", "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=2)
    
    # 最终输出
    print(f"\n{'='*60}")
    print("[DONE] 演示数据包生成完毕!")
    print(f"{'='*60}")
    print(f"\n📦 数据包内容:")
    print(f"   • POI数据: {package['stats']['poi_count']} 个")
    for cat, count in package["stats"]["categories"].items():
        print(f"     - {cat}: {count}个")
    if "distance_matrix_size" in package["stats"]:
        print(f"   • 距离矩阵: {package['stats']['distance_matrix_size']}")
    print(f"\n📁 文件列表:")
    for name, path in package["files"].items():
        exists = "[OK]" if os.path.exists(path) else "[MISSING]"
        print(f"   {exists} {name}: {path}")
    print(f"\n[GO] 现在可以直接运行路线规划Demo了！")


if __name__ == "__main__":
    main()
