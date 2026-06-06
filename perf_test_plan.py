# -*- coding: utf-8 -*-
"""
路线生成性能测试脚本（方案A - 黑盒API测试变体）
直接调用 planner_service.plan()，记录各阶段时间戳，同时保留后端日志输出用于交叉验证。
"""
import os
import sys
import time

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')

from backend.models.schemas import PlanRequest
from backend.services.planner import planner_service

# 重定向标准输出，同时打印到屏幕和日志文件
import io

class TeeIO:
    def __init__(self, stream, filepath):
        self.stream = stream
        self.file = open(filepath, 'w', encoding='utf-8')
    def write(self, data):
        self.stream.write(data)
        self.file.write(data)
        self.file.flush()
    def flush(self):
        self.stream.flush()
        self.file.flush()

sys.stdout = TeeIO(sys.stdout, 'perf_test_output.log')
sys.stderr = TeeIO(sys.stderr, 'perf_test_error.log')

def test_case(name, raw_query, preferences, travelers='情侣', pace='适中', budget=500):
    print(f"\n{'='*70}")
    print(f"测试用例: {name}")
    print(f"raw_query: {raw_query}")
    print(f"preferences: {preferences}")
    print(f"启动时间: {time.strftime('%H:%M:%S')}")
    
    req = PlanRequest(
        raw_query=raw_query,
        city='杭州',
        start_time='09:00',
        end_time='18:00',
        budget=budget,
        travelers=travelers,
        preferences=preferences,
        pace=pace,
        transport_mode='步行'
    )
    
    t0 = time.time()
    try:
        resp = planner_service.plan(req, user_id=None)
        t1 = time.time()
        total = t1 - t0
        print(f"\n[结果] 总耗时: {total:.2f}s")
        print(f"[结果] 生成方案数: {len(resp.plans)}")
        for p in resp.plans:
            cats = {}
            for s in p.segments:
                cats[s.poi.category] = cats.get(s.poi.category, 0) + 1
            print(f"  [{p.theme}] {p.poi_count}POIs ¥{p.total_cost} | 分布: {cats}")
        return total
    except Exception as e:
        t1 = time.time()
        print(f"\n[错误] {e}")
        print(f"[结果] 异常耗时: {t1-t0:.2f}s")
        return t1 - t0

# 预热：加载模型和数据
print("="*70)
print("预热: 加载模型和POI数据")
tw = time.time()
from backend.data.loader import get_cached_pois
from backend.core.semantic_matcher import semantic_matcher
pois = get_cached_pois('杭州')
for p in pois:
    semantic_matcher.get_poi_embedding(p)
print(f"预热完成，耗时: {time.time()-tw:.2f}s")

# 测试1: 无 raw_query（纯标签）
t1 = test_case('纯标签-无raw_query', raw_query='', preferences=['美食', '拍照'])

# 测试2: 有 raw_query（美食+拍照）
t2 = test_case('自然语言-美食拍照', raw_query='周末带女朋友去杭州玩，喜欢拍照和吃辣', preferences=['拍照', '美食'])

# 测试3: 有 raw_query（亲子户外）
t3 = test_case('自然语言-亲子户外', raw_query='带小孩去杭州，要游乐园和户外活动', preferences=['娱乐', '自然'])

# 测试4: 有 raw_query（购物）
t4 = test_case('自然语言-购物', raw_query='去杭州购物逛街，买衣服买化妆品', preferences=['购物'])

# 汇总
print("\n" + "="*70)
print("性能测试汇总")
print("="*70)
print(f"纯标签(无raw_query):     {t1:.2f}s")
print(f"自然语言(美食+拍照):      {t2:.2f}s")
print(f"自然语言(亲子户外):       {t3:.2f}s")
print(f"自然语言(购物):           {t4:.2f}s")
print("="*70)
print("测试完成。详细日志见 perf_test_output.log")
