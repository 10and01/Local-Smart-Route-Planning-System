#!/usr/bin/env python3
"""阶段3测评：个性化效果离线评测 + LLM偏好解析增强"""

from backend.core.personalization_eval import run_batch_evaluation, print_evaluation_report
from backend.core.llm_parser import parse_preference_from_llm

print("=" * 60)
print("阶段3测评：个性化效果离线评测 + LLM偏好解析增强")
print("=" * 60)

# 1. 个性化效果评测
print("\n[1/2] 个性化效果离线评测")
report = run_batch_evaluation(city="杭州")
print_evaluation_report(report)

# 2. LLM偏好解析增强测试
print("\n[2/2] LLM偏好解析增强测试")

test_cases = [
    {
        "query": "我喜欢拍照，但不喜欢排队，预算200以内",
        "prefs": ["拍照"],
        "travelers": "独自",
        "pace": "适中",
        "budget": 200,
        "expected_queue_low": True,
        "expected_budget_economic": True,
    },
    {
        "query": "周末带小孩去杭州，想爬山和看博物馆",
        "prefs": ["自然", "文化"],
        "travelers": "亲子",
        "pace": "适中",
        "budget": 500,
        "expected_traveler": "亲子",
        "expected_nature_high": True,
    },
    {
        "query": "情侣出游，喜欢浪漫的地方，避开人多的景点",
        "prefs": ["拍照"],
        "travelers": "情侣",
        "pace": "悠闲",
        "budget": 500,
        "expected_traveler": "情侣",
        "expected_queue_low": True,
    },
]

llm_passed = 0
llm_total = 0

for tc in test_cases:
    print(f"\n  Query: {tc['query']}")
    result = parse_preference_from_llm(
        raw_query=tc["query"],
        preferences=tc["prefs"],
        travelers=tc["travelers"],
        pace=tc["pace"],
        budget=tc["budget"],
    )
    if not result:
        print("    [FAIL] 解析失败")
        continue

    checks = []
    if tc.get("expected_queue_low"):
        llm_total += 1
        if result.willingness_to_queue < 0.3:
            checks.append("    [PASS] 负面偏好'不喜欢排队'正确识别 (queue<0.3)")
            llm_passed += 1
        else:
            checks.append(f"    [FAIL] 排队意愿过高: {result.willingness_to_queue}")

    if tc.get("expected_budget_economic"):
        llm_total += 1
        if result.budget_level == "经济":
            checks.append("    [PASS] 预算约束正确识别 (经济)")
            llm_passed += 1
        else:
            checks.append(f"    [FAIL] 预算级别错误: {result.budget_level}")

    if tc.get("expected_traveler"):
        llm_total += 1
        if result.traveler_type == tc["expected_traveler"]:
            checks.append(f"    [PASS] 人群约束正确识别 ({result.traveler_type})")
            llm_passed += 1
        else:
            checks.append(f"    [FAIL] 人群错误: {result.traveler_type}")

    if tc.get("expected_nature_high"):
        llm_total += 1
        if result.theme_weights.get("自然", 0) > 0.5:
            checks.append(f"    [PASS] 自然偏好正确识别 ({result.theme_weights.get('自然')})")
            llm_passed += 1
        else:
            checks.append(f"    [FAIL] 自然偏好过低: {result.theme_weights.get('自然')}")

    for c in checks:
        print(c)

print(f"\nLLM偏好解析通过: {llm_passed}/{llm_total}")

print("\n" + "=" * 60)
print("阶段3通过标准:")
overall_passed = sum(1 for s in report["summary_by_profile"].values() if s["avg_diff_score"] > 0.2)
print(f"  [{'PASS' if overall_passed >= 5 else 'FAIL'}] 至少5种画像类型的平均 diff_score > 0.2 ({overall_passed}/6)")
print(f"  [{'PASS' if llm_passed >= max(1, llm_total * 0.7) else 'FAIL'}] LLM偏好解析正确识别负面偏好 ({llm_passed}/{llm_total})")
print("=" * 60)
