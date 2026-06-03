#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德真实POI + LLM丰富化 完整流程脚本
一键完成：拉取 -> 丰富化 -> 计算距离矩阵

用法:
    python scripts/build_real_pois_pipeline.py
    python scripts/build_real_pois_pipeline.py --skip-fetch  # 跳过拉取（已有raw数据）
    python scripts/build_real_pois_pipeline.py --city 杭州 --max-per-type 30
"""

import os
import sys
import subprocess
import argparse

# Windows控制台UTF-8编码修复
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def run_command(cmd: list, description: str):
    """运行子命令并打印输出"""
    print(f"\n{'='*60}")
    print(f"▶ {description}")
    print(f"{'='*60}")
    
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=False,
        text=True,
        encoding="utf-8"
    )
    
    if result.returncode != 0:
        print(f"❌ {description} 失败，退出码: {result.returncode}")
        return False
    
    print(f"✅ {description} 完成")
    return True


def check_amap_key():
    """检查是否配置了高德API Key"""
    key = os.getenv("AMAP_KEY", "")
    if key and key != "YOUR_AMAP_KEY_HERE":
        return True
    
    # 检查脚本中是否有硬编码的key
    fetch_script = os.path.join(PROJECT_ROOT, "scripts", "fetch_pois_amap.py")
    with open(fetch_script, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "YOUR_AMAP_KEY_HERE" not in content:
        # 可能被替换了，尝试运行看看
        return True
    
    return False


def main():
    parser = argparse.ArgumentParser(description="高德真实POI完整流程")
    parser.add_argument("--city", default="杭州", help="目标城市")
    parser.add_argument("--max-per-type", type=int, default=30, help="每类POI最多拉取条数")
    parser.add_argument("--batch-size", type=int, default=5, help="LLM丰富化batch大小")
    parser.add_argument("--skip-fetch", action="store_true", help="跳过高德拉取（已有raw数据）")
    parser.add_argument("--skip-matrix", action="store_true", help="跳过距离矩阵计算")
    parser.add_argument("--matrix-method", choices=["osrm", "haversine"], default="osrm",
                        help="距离矩阵计算方法")
    args = parser.parse_args()
    
    city = args.city
    raw_file = os.path.join(DATA_DIR, f"{city}_pois_amap_raw.json")
    enriched_file = os.path.join(DATA_DIR, f"{city}_pois.json")
    
    print("🚀 启动高德真实POI + LLM丰富化流程")
    print(f"   城市: {city}")
    print(f"   项目根目录: {PROJECT_ROOT}")
    
    # Step 1: 拉取高德POI
    if not args.skip_fetch:
        if not check_amap_key():
            print("\n⚠️ 未检测到高德API Key！")
            print("   请执行以下操作之一：")
            print("   1. 设置环境变量: export AMAP_KEY=你的key")
            print("   2. 修改 scripts/fetch_pois_amap.py 中的 AMAP_KEY")
            print("   3. 使用 --skip-fetch 跳过拉取（如果已有raw数据）")
            print("\n   申请地址: https://lbs.amap.com/dev/key/app")
            return 1
        
        if not run_command(
            [sys.executable, "scripts/fetch_pois_amap.py"],
            f"Step 1/3: 从高德API拉取 {city} POI数据"
        ):
            return 1
        
        if not os.path.exists(raw_file):
            print(f"❌ 拉取失败，未找到文件: {raw_file}")
            return 1
    else:
        print("\n⏭️ 跳过高德拉取（--skip-fetch）")
        if not os.path.exists(raw_file):
            print(f"❌ 未找到raw文件: {raw_file}")
            return 1
    
    # Step 2: LLM丰富化
    if not run_command(
        [sys.executable, "scripts/enrich_pois_by_llm.py",
         "--input", raw_file,
         "--output", enriched_file,
         "--batch-size", str(args.batch_size)],
        "Step 2/3: LLM丰富化POI数据"
    ):
        return 1
    
    if not os.path.exists(enriched_file):
        print(f"❌ 丰富化失败，未找到文件: {enriched_file}")
        return 1
    
    # Step 3: 计算距离矩阵
    if not args.skip_matrix:
        if args.matrix_method == "osrm":
            if not run_command(
                [sys.executable, "scripts/compute_distance_matrix_osrm_table.py",
                 "--input", enriched_file],
                "Step 3/3: 计算OSRM真实距离矩阵"
            ):
                print("⚠️ OSRM矩阵计算失败，尝试Haversine回退...")
                if not run_command(
                    [sys.executable, "scripts/compute_distance_matrix.py",
                     "--input", enriched_file,
                     "--method", "haversine"],
                    "Step 3/3: 计算Haversine距离矩阵（回退）"
                ):
                    return 1
        else:
            if not run_command(
                [sys.executable, "scripts/compute_distance_matrix.py",
                 "--input", enriched_file,
                 "--method", "haversine"],
                "Step 3/3: 计算Haversine距离矩阵"
            ):
                return 1
    else:
        print("\n⏭️ 跳过距离矩阵计算（--skip-matrix）")
    
    # 完成
    print(f"\n{'='*60}")
    print("🎉 全部完成！")
    print(f"{'='*60}")
    print(f"   丰富化POI文件: {enriched_file}")
    print(f"   后端会自动加载此文件（优先级高于mock数据）")
    print(f"\n   下一步建议:")
    print(f"   1. 重启后端服务以加载新数据")
    print(f"   2. 运行测试: python tests/e2e_test.py")
    print(f"   3. 访问前端验证效果")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
