# -*- coding: utf-8 -*-
"""
后端实时监控脚本
读取 backend_live.log，提取关键性能指标
"""
import os
import sys
import time
import re
from collections import defaultdict

LOG_FILE = "backend_live.log"

# 关键日志模式
PATTERNS = {
    "llm_quota": re.compile(r"\[CategoryQuota\] LLM动态配额:\s*(.+)$"),
    "llm_quota_fail": re.compile(r"\[CategoryQuota\] LLM动态配额失败"),
    "llm_filter_fail": re.compile(r"\[LLM Filter Warning\] LLM 筛选失败"),
    "llm_skeleton_fail": re.compile(r"\[Planner\] LLM骨架规划失败"),
    "llm_rerank_ok": re.compile(r"\[Planner\] LLM rerank completed"),
    "llm_policy_ok": re.compile(r"\[Planner\] Policy generated"),
    "llm_reason_fail": re.compile(r"\[Planner\] .+ 推荐理由超时或失败"),
    "api_plan": re.compile(r'POST /api/plan HTTP/1\.1" (\d+)'),
    "filter_result": re.compile(r"\[Planner\] 筛选策略: .+ 输入(\d+) → 输出(\d+)"),
    "dynamic_fetch": re.compile(r"\[Planner\] 动态抓取补充 (\d+) 个新POI"),
    "perf_dynamic_fetch": re.compile(r"\[Perf\] DynamicFetch 总耗时:\s*([\d.]+)s"),
}

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def analyze_log(filepath):
    if not os.path.exists(filepath):
        return {"error": "日志文件不存在"}
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        return {"error": str(e)}
    
    stats = {
        "total_lines": len(lines),
        "api_plan_requests": 0,
        "api_plan_success": 0,
        "api_plan_fail": 0,
        "llm_quota_ok": 0,
        "llm_quota_fail": 0,
        "llm_filter_fail": 0,
        "llm_skeleton_fail": 0,
        "llm_rerank_ok": 0,
        "llm_policy_ok": 0,
        "llm_reason_fail": 0,
        "dynamic_fetch_count": 0,
        "filter_input_output": [],
        "latest_lines": [],
    }
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # API /api/plan 请求
        m = PATTERNS["api_plan"].search(line)
        if m:
            stats["api_plan_requests"] += 1
            status = m.group(1)
            if status == "200":
                stats["api_plan_success"] += 1
            else:
                stats["api_plan_fail"] += 1
        
        # LLM 动态配额
        if PATTERNS["llm_quota"].search(line):
            stats["llm_quota_ok"] += 1
        if PATTERNS["llm_quota_fail"].search(line):
            stats["llm_quota_fail"] += 1
        
        # LLM 筛选失败
        if PATTERNS["llm_filter_fail"].search(line):
            stats["llm_filter_fail"] += 1
        
        # LLM 骨架规划失败
        if PATTERNS["llm_skeleton_fail"].search(line):
            stats["llm_skeleton_fail"] += 1
        
        # LLM Rerank 成功
        if PATTERNS["llm_rerank_ok"].search(line):
            stats["llm_rerank_ok"] += 1
        
        # Policy 生成成功
        if PATTERNS["llm_policy_ok"].search(line):
            stats["llm_policy_ok"] += 1
        
        # 推荐理由失败
        if PATTERNS["llm_reason_fail"].search(line):
            stats["llm_reason_fail"] += 1
        
        # 动态抓取
        m = PATTERNS["dynamic_fetch"].search(line)
        if m:
            stats["dynamic_fetch_count"] = int(m.group(1))
        
        # 筛选输入输出
        m = PATTERNS["filter_result"].search(line)
        if m:
            stats["filter_input_output"].append((int(m.group(1)), int(m.group(2))))
    
    # 最近20行日志
    stats["latest_lines"] = [l.strip() for l in lines[-20:] if l.strip()]
    
    return stats

def print_dashboard(stats):
    clear_screen()
    print("=" * 70)
    print("后端实时监控面板")
    print("=" * 70)
    print(f"日志总行数: {stats.get('total_lines', 0)}")
    print()
    
    print("[API 请求]")
    print(f"  /api/plan 总请求: {stats.get('api_plan_requests', 0)}")
    print(f"  成功 (200):       {stats.get('api_plan_success', 0)}")
    print(f"  失败:             {stats.get('api_plan_fail', 0)}")
    print()
    
    print("[LLM 调用统计]")
    print(f"  动态配额成功:     {stats.get('llm_quota_ok', 0)}")
    print(f"  动态配额失败:     {stats.get('llm_quota_fail', 0)}")
    print(f"  筛选失败:         {stats.get('llm_filter_fail', 0)}")
    print(f"  骨架规划失败:     {stats.get('llm_skeleton_fail', 0)}")
    print(f"  Rerank 成功:      {stats.get('llm_rerank_ok', 0)}")
    print(f"  Policy 成功:      {stats.get('llm_policy_ok', 0)}")
    print(f"  推荐理由失败:     {stats.get('llm_reason_fail', 0)}")
    print()
    
    print("[筛选结果]")
    for inp, out in stats.get("filter_input_output", [])[-3:]:
        print(f"  输入 {inp} → 输出 {out}")
    print()
    
    print("[最近日志]")
    for line in stats.get("latest_lines", [])[-10:]:
        # 截断长行
        if len(line) > 100:
            line = line[:97] + "..."
        print(f"  {line}")
    
    print("=" * 70)
    print(f"刷新时间: {time.strftime('%H:%M:%S')} | 按 Ctrl+C 停止")
    print("=" * 70)

if __name__ == "__main__":
    print(f"开始监控: {LOG_FILE}")
    print("等待日志生成...")
    
    try:
        while True:
            stats = analyze_log(LOG_FILE)
            print_dashboard(stats)
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n监控已停止")
        sys.exit(0)
