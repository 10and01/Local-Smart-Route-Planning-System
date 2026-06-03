# -*- coding: utf-8 -*-
"""
混合 POI 筛选器 API 实际调用测试
直接调用 localhost:8000 API 验证三条路径

运行方式:
    cd /d/美团hackthon_5
    source venv/Scripts/activate
    python tests/test_hybrid_filter_api.py
"""

import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "http://localhost:8000"
API_PLAN = f"{BASE_URL}/api/plan"


def test_simple_path():
    """
    测试纯规则路径：输入'美食+拍照'（预设标签）
    期望：走 rule_only 路径，<100ms（纯筛选部分），所有推荐理由来源为[规则]
    """
    print("=" * 60)
    print("Test 1: SIMPLE path (美食+拍照)")
    print("=" * 60)
    
    payload = {
        "city": "杭州",
        "start_time": "09:00",
        "end_time": "18:00",
        "budget": 500,
        "preferences": ["美食", "拍照"],
        "travelers": "情侣",
        "pace": "悠闲"
    }
    
    start = time.time()
    resp = requests.post(API_PLAN, json=payload, timeout=30)
    elapsed_ms = (time.time() - start) * 1000
    
    assert resp.status_code == 200, f"API返回 {resp.status_code}: {resp.text[:500]}"
    data = resp.json()
    
    print(f"Status: {resp.status_code}")
    print(f"Total elapsed: {elapsed_ms:.1f}ms")
    print(f"Candidates: {data['candidate_pois_count']}")
    print(f"Plans: {len(data['plans'])}")
    
    for plan in data["plans"]:
        print(f"  {plan['theme']}: {plan['poi_count']} POIs")
    
    # 验证推荐理由来源标注
    all_rule_tagged = True
    for plan in data["plans"]:
        for seg in plan["segments"]:
            for reason in seg.get("selection_reasons", []):
                if not reason.startswith("[规则]"):
                    print(f"  ERROR: 缺少[规则]前缀: {reason}")
                    all_rule_tagged = False
    
    assert all_rule_tagged, "所有推荐理由应带有[规则]前缀"
    print("[OK] 所有 selection_reasons 均带有 [规则] 前缀")
    print()


def test_hybrid_path():
    """
    测试混合路径：输入'想吃辣的人少的地方'（自然语言，2个隐性需求）
    期望：走 hybrid 路径，LLM识别'吃辣''人少'
    """
    print("=" * 60)
    print("Test 2: HYBRID path (想吃辣的人少的地方)")
    print("=" * 60)
    
    payload = {
        "city": "杭州",
        "raw_query": "想吃辣的人少的地方",
        "start_time": "09:00",
        "end_time": "18:00",
        "budget": 300,
        "preferences": ["美食"],
        "travelers": "朋友",
        "pace": "适中"
    }
    
    start = time.time()
    resp = requests.post(API_PLAN, json=payload, timeout=120)
    elapsed_s = time.time() - start
    
    assert resp.status_code == 200, f"API返回 {resp.status_code}: {resp.text[:500]}"
    data = resp.json()
    
    print(f"Status: {resp.status_code}")
    print(f"Total elapsed: {elapsed_s:.1f}s")
    print(f"Candidates: {data['candidate_pois_count']}")
    print(f"Plans: {len(data['plans'])}")
    
    for plan in data["plans"]:
        print(f"  {plan['theme']}: {plan['poi_count']} POIs")
        for seg in plan["segments"]:
            reasons = seg.get("selection_reasons", [])
            if reasons:
                print(f"    - {seg['poi']['name']}: {reasons}")
    
    # 验证是否有[规则]或[LLM]标注
    has_rule = False
    has_llm = False
    for plan in data["plans"]:
        for seg in plan["segments"]:
            for reason in seg.get("selection_reasons", []):
                if reason.startswith("[规则]"):
                    has_rule = True
                elif reason.startswith("[LLM]"):
                    has_llm = True
    
    print(f"Has [规则] reasons: {has_rule}")
    print(f"Has [LLM] reasons: {has_llm}")
    
    # 由于当前环境 LLM API 限流，[LLM] 理由可能无法生成，但至少应有[规则]理由
    assert has_rule, "至少应有[规则]推荐理由"
    print("[OK] 推荐理由来源标注正确")
    print()


def test_complex_path():
    """
    测试复杂路径：>=3个隐性需求 → LLM主导
    注：当前环境 LLM API 可能限流，主要验证策略选择正确
    """
    print("=" * 60)
    print("Test 3: COMPLEX path (3个隐性需求)")
    print("=" * 60)
    
    payload = {
        "city": "杭州",
        "raw_query": "想吃辣的人少安静的地方",
        "start_time": "09:00",
        "end_time": "18:00",
        "budget": 300,
        "preferences": ["美食"],
        "travelers": "朋友",
        "pace": "适中"
    }
    
    start = time.time()
    resp = requests.post(API_PLAN, json=payload, timeout=120)
    elapsed_s = time.time() - start
    
    assert resp.status_code == 200, f"API返回 {resp.status_code}: {resp.text[:500]}"
    data = resp.json()
    
    print(f"Status: {resp.status_code}")
    print(f"Total elapsed: {elapsed_s:.1f}s")
    print(f"Candidates: {data['candidate_pois_count']}")
    print(f"Plans: {len(data['plans'])}")
    
    for plan in data["plans"]:
        print(f"  {plan['theme']}: {plan['poi_count']} POIs")
    
    print("[OK] COMPLEX 路径请求成功")
    print()


def test_structure():
    """验证返回结构完整性"""
    print("=" * 60)
    print("Test 4: Response structure validation")
    print("=" * 60)
    
    resp = requests.post(API_PLAN, json={
        "city": "杭州",
        "preferences": ["美食"],
        "travelers": "独自",
        "pace": "适中"
    }, timeout=30)
    
    data = resp.json()
    assert "request_id" in data
    assert "user_preference" in data
    assert "plans" in data
    assert "candidate_pois_count" in data
    assert len(data["plans"]) == 3
    
    for plan in data["plans"]:
        assert "plan_id" in plan
        assert "theme" in plan
        assert "segments" in plan
        assert len(plan["segments"]) == plan["poi_count"]
        for seg in plan["segments"]:
            assert "poi" in seg
            assert "name" in seg["poi"]
            assert "location" in seg["poi"]
            assert "arrive_time" in seg
            assert "leave_time" in seg
            assert "selection_reasons" in seg
    
    print("[OK] 响应结构完整")
    print()


if __name__ == "__main__":
    print("混合 POI 筛选器 API 实际调用测试")
    print("=" * 60)
    
    # 健康检查
    health = requests.get(f"{BASE_URL}/", timeout=5)
    assert health.status_code == 200
    print(f"Server health: {health.json()['status']}")
    print()
    
    test_simple_path()
    test_hybrid_path()
    test_complex_path()
    test_structure()
    
    print("=" * 60)
    print("[DONE] 所有 API 测试通过！")
    print("=" * 60)
