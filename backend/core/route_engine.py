# -*- coding: utf-8 -*-
"""
偏好驱动的路线规划引擎
核心算法实现：
  1. 偏好引导的贪心构造
  2. 偏好引导的2-opt优化
  3. 多方案生成（体验优先 / 效率优先 / 均衡）
"""

import math
import copy
import os
import json
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime, timedelta

from backend.models.schemas import (
    POI, Location, UserPreference, RouteConstraints, 
    RoutePlan, PlanSegment
)
from backend.core.preference import (
    compute_preference_match, compute_crowd_match, record_selection_reason
)
from backend.data.loader import get_matrix_provider
from backend.core.policy_generator import (
    PlanningPolicy, get_strategy_config, get_effective_coefficient
)


# ============================================================================
# LLM 去重与餐饮插入辅助函数
# ============================================================================

# 模块级缓存：同一批POI只去重一次
_dedup_cache: Dict[str, List[POI]] = {}


def _deduplicate_pois(candidates: List[POI], city: str) -> List[POI]:
    """
    对候选POI进行轻量级规则去重，主要处理风景名胜类的重叠子景点。
    LLM深度过滤已在数据抓取阶段完成，规划阶段只做规则去重避免超时。
    
    策略：
    1. 名称包含关系去重（如"西湖-花港观鱼"和"花港观鱼"保留前者）
    2. 距离<500m的去重（保留rating更高的）
    """
    if not candidates:
        return candidates
    
    # 用poi_id列表做缓存key
    cache_key = ','.join(sorted(p.poi_id for p in candidates if p.poi_id))
    if cache_key in _dedup_cache:
        return _dedup_cache[cache_key]
    
    # Step 1: 名称包含关系去重
    name_map = {}  # name -> poi
    to_remove = set()
    for p in candidates:
        name = p.name.strip()
        for other_name, other_p in list(name_map.items()):
            if name != other_name and (name in other_name or other_name in name):
                if len(other_name) > len(name):
                    to_remove.add(id(p))
                else:
                    to_remove.add(id(other_p))
                    name_map[name] = p
                    del name_map[other_name]
                break
        else:
            name_map[name] = p
    
    filtered = [p for p in candidates if id(p) not in to_remove]
    
    # Step 2: 风景名胜类近距离去重（<500m保留rating更高的）
    scenic = [p for p in filtered if p.category == "风景名胜"]
    others = [p for p in filtered if p.category != "风景名胜"]
    
    keep_scenic = []
    removed_scenic_ids = set()
    for i, p1 in enumerate(scenic):
        if id(p1) in removed_scenic_ids:
            continue
        cluster = [p1]
        for j, p2 in enumerate(scenic):
            if i != j and id(p2) not in removed_scenic_ids:
                dist = haversine_distance_m(
                    p1.location.lat, p1.location.lng,
                    p2.location.lat, p2.location.lng
                )
                if dist < 500:
                    cluster.append(p2)
        cluster.sort(key=lambda p: (p.rating or 0, len(p.name)), reverse=True)
        # 距离<200m的cluster只保留1个（避免灵隐寺+灵隐景区重复），200-500m保留2个
        min_dist = min(
            haversine_distance_m(cluster[0].location.lat, cluster[0].location.lng, p.location.lat, p.location.lng)
            for p in cluster[1:]
        ) if len(cluster) > 1 else 9999
        keep_count = 1 if min_dist < 200 else 2
        keep = cluster[:keep_count]
        keep_scenic.extend(keep)
        for p in cluster:
            removed_scenic_ids.add(id(p))
    
    result = keep_scenic + others
    _dedup_cache[cache_key] = result
    return result


def _llm_filter_low_quality_scenic(candidates: List[POI], city: str) -> List[POI]:
    """
    用LLM对风景名胜类POI进行快速过滤，删除旅游价值低（<3分）的POI。
    分批处理，每批15个避免超时。
    """
    scenic = [p for p in candidates if p.category == "风景名胜"]
    if len(scenic) <= 30:
        # POI数量少时不调用LLM，直接返回
        return candidates
    
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "")
        )
        model = os.getenv("LLM_MODEL_NAME", "")
        if not model:
            return candidates
    except Exception:
        return candidates
    
    names = [p.name for p in scenic]
    low_score_names = set()
    batch_size = 15
    
    for i in range(0, len(names), batch_size):
        batch = names[i:i + batch_size]
        prompt = f'''你是一位资深旅游专家。以下是从高德地图抓取的{city}景点列表。

请判断每个景点对游客（尤其是第一次去{city}的外地游客）的推荐价值，按1-5分打分：
- 5分：全国/省级知名地标，必去景点
- 4分：市内知名景点，值得专程前往  
- 3分：区域小众景点，顺路可去
- 2分：本地休闲场所，游客不必去
- 1分：完全不适合旅游推荐

请严格按JSON数组输出，只输出JSON（name必须完全匹配输入）：
[{{"name": "...", "score": N}}]

景点列表：
''' + '\n'.join(batch)

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "旅游专家，严格JSON输出，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                timeout=30,
            )
            content = resp.choices[0].message.content
            import re
            m = re.search(r'\[.*\]', content, re.DOTALL)
            if m:
                result = json.loads(m.group())
                for item in result:
                    if item.get("score", 3) < 3:
                        low_score_names.add(item["name"])
        except Exception:
            pass
    
    filtered_scenic = [p for p in scenic if p.name not in low_score_names]
    others = [p for p in candidates if p.category != "风景名胜"]
    return filtered_scenic + others


def _force_insert_meals(
    segments: List[PlanSegment],
    all_candidates: List[POI],
    constraints: RouteConstraints,
    end_dt: Optional[datetime] = None,
    user_pref: Optional[UserPreference] = None,
    policy: Optional[Any] = None,
) -> List[PlanSegment]:
    """
    强制在路线中插入午餐/晚餐时段的餐饮POI。
    
    策略：
    1. 检查路线中是否已有餐饮POI（category == "餐饮服务"）
    2. 如果没有，在午餐窗口（11:30-13:30）和晚餐窗口（17:30-19:30）附近插入
    3. 从all_candidates中选择未使用的、距离最近的餐饮POI
    4. 插入后segment顺序自动调整
    """
    if not segments or not all_candidates:
        return segments
    
    # 识别已有餐饮POI
    has_lunch = False
    has_dinner = False
    for seg in segments:
        if seg.poi.category == "餐饮服务":
            arrive_h = parse_time(seg.arrive_time).hour
            if 11 <= arrive_h <= 14:
                has_lunch = True
            if 17 <= arrive_h <= 20:
                has_dinner = True
    
    # 获取已使用的POI ID
    used_ids = {seg.poi.poi_id for seg in segments}
    
    # 计算当前总花费
    current_total_cost = sum(seg.poi.price or 0 for seg in segments)
    budget = constraints.budget

    # 筛选可用餐饮POI，并排除明显超预算的
    food_candidates = [
        p for p in all_candidates
        if p.category == "餐饮服务" and p.poi_id not in used_ids
    ]
    if not food_candidates:
        return segments

    # 【阶段二】预算约束：如果预算有限，优先排除高价餐厅
    if budget and budget > 0:
        max_single = budget * 0.35  # 单餐不超过预算35%（500元→175元）
        food_candidates = [p for p in food_candidates if (p.price or 0) <= max_single]
        if not food_candidates:
            return segments
    
    def find_best_restaurant(reference_seg: PlanSegment) -> Optional[POI]:
        """找到距离reference_seg最近、符合预算且偏好匹配度最高的餐厅"""
        best = None
        best_score = float('inf')
        for r in food_candidates:
            dist = haversine_distance_m(
                reference_seg.poi.location.lat, reference_seg.poi.location.lng,
                r.location.lat, r.location.lng
            )
            # 基础分数：距离 / rating（越小越好）
            base_score = dist / max(r.rating or 3.0, 1.0)
            if budget and budget > 0 and (r.price or 0) > budget * 0.25:
                base_score *= 2.0  # 高价餐厅距离惩罚翻倍
            
            # 【修复】偏好匹配奖励： Policy 自由维度偏好匹配度高的餐厅优先
            pref_bonus = 0.0
            if policy is not None and user_pref is not None:
                effective_theme_weights = dict(user_pref.theme_weights)
                policy_themes = policy.preference_space.get("theme_weights", {})
                if policy_themes:
                    for dimension, weight in policy_themes.items():
                        effective_theme_weights[dimension] = max(
                            effective_theme_weights.get(dimension, 0),
                            float(weight)
                        )
                for dimension, weight in effective_theme_weights.items():
                    keywords = policy.theme_keyword_map.get(dimension, [dimension])
                    match_score = _compute_keyword_match_score(r, keywords)
                    if match_score > 0:
                        pref_bonus -= weight * match_score * 500  # 负值=奖励
            
            total_score = base_score + pref_bonus
            if total_score < best_score:
                best_score = total_score
                best = r
        return best
    
    def insert_after(segments: List[PlanSegment], idx: int, poi: POI, transport_mode: str) -> List[PlanSegment]:
        """在idx位置后插入新segment"""
        new_seg = PlanSegment(
            poi=poi,
            arrive_time="12:00",  # 临时值，后面会重新计算
            leave_time="13:00",
            duration=60,
            transport_to_next=None,
            transport_distance_m=0,
            transport_mode=transport_mode,
        )
        segments.insert(idx + 1, new_seg)
        return segments
    
    transport_mode = constraints.transport_mode or "步行"
    
    # 根据路线长度决定插入策略
    route_duration_min = 0
    if segments:
        first_arrive = parse_time(segments[0].arrive_time)
        last_leave = parse_time(segments[-1].leave_time)
        route_duration_min = int((last_leave - first_arrive).total_seconds() / 60)
    
    # 短路线（< 4小时）只插入1个餐饮；长路线尝试插入2个
    skip_dinner = route_duration_min < 240
    
    # 插入午餐
    if not has_lunch:
        # 找到最接近12:00的segment
        best_idx = -1
        best_diff = float('inf')
        for i, seg in enumerate(segments):
            arrive_h = parse_time(seg.arrive_time).hour
            diff = abs(arrive_h - 12)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        
        if best_idx >= 0:
            rest = find_best_restaurant(segments[best_idx])
            # 【阶段二】插入前检查总预算
            if rest and (not budget or current_total_cost + (rest.price or 0) <= budget * 0.9):
                segments = insert_after(segments, best_idx, rest, transport_mode)
                current_total_cost += rest.price or 0
                food_candidates.remove(rest)
    
    # 插入晚餐
    if not has_dinner and not skip_dinner:
        best_idx = -1
        best_diff = float('inf')
        for i, seg in enumerate(segments):
            arrive_h = parse_time(seg.arrive_time).hour
            diff = abs(arrive_h - 18)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        
        if best_idx >= 0:
            rest = find_best_restaurant(segments[best_idx])
            # 【阶段二】插入前检查总预算
            if rest and (not budget or current_total_cost + (rest.price or 0) <= budget * 0.9):
                # 【Phase Four】估算插入晚餐后是否严重超时
                if end_dt:
                    # 简化估算：插入晚餐会使后续POI后移约70分钟
                    poi_after = len(segments) - best_idx - 1
                    estimated_shift = 70 + poi_after * 5
                    last_leave = parse_time(segments[-1].leave_time)
                    if last_leave + timedelta(minutes=estimated_shift) > end_dt + timedelta(minutes=15):
                        pass  # 预计超时，跳过晚餐
                    else:
                        segments = insert_after(segments, best_idx, rest, transport_mode)
                        current_total_cost += rest.price or 0
                else:
                    segments = insert_after(segments, best_idx, rest, transport_mode)
                    current_total_cost += rest.price or 0
    
    return segments


def _pre_filter_by_budget(candidates: List[POI], budget: Optional[int]) -> List[POI]:
    """
    候选池预过滤：排除明显超预算的POI
    【阶段二】预算硬约束：单个POI价格超过预算一定比例时直接排除
    """
    if not budget or budget <= 0:
        return candidates
    # 宽松阈值：允许单点最多占预算的60%（如500元预算排除>300元的餐厅）
    # 对于高预算适当放宽
    threshold = budget * 0.6 if budget < 1000 else budget * 0.4
    filtered = []
    for poi in candidates:
        price = poi.price
        if price is not None and price > threshold:
            continue
        filtered.append(poi)
    return filtered


# ============================================================================
# 三层差异化策略配置
# ============================================================================

# 模块级别变量，用于在规划过程中传递当前城市（供距离矩阵查询使用）
_current_planning_city: str = "杭州"
# 三种方案使用完全不同的策略参数，从候选集、选择策略、优化目标三个层面
# 物理上保证路线差异化
STRATEGY_CONFIG = {
    "experience": {
        "name": "深度体验",
        "description": "专注你最感兴趣的偏好，允许绕路去高体验POI",
        "max_distance_from_start_km": 100,   # 【重构】大幅放宽，几乎不限制
        "candidate_count": 35,
        "pref_match_boost": 2.0,
        "time_penalty_factor": 0.5,
        "max_travel_km_per_step": 30,        # 【重构】支持地铁/驾车远郊跳跃
        "max_total_route_km": 100,
        "min_poi_count": 4,
        "two_opt_pref_weight": 1.0,
        "distance_weight": 0.4,
    },
    "efficiency": {
        "name": "高效省时",
        "description": "严格短距离，用最短时间打卡最多亮点",
        "max_distance_from_start_km": 100,   # 【重构】候选集不限制距离
        "candidate_count": 25,
        "pref_match_boost": 0.5,
        "time_penalty_factor": 2.0,
        "max_travel_km_per_step": 15,        # 【重构】由贪心算法自然约束
        "max_total_route_km": 50,
        "min_poi_count": 4,
        "two_opt_pref_weight": 0.0,
        "distance_weight": 1.2,
    },
    "balanced": {
        "name": "均衡推荐",
        "description": "兼顾体验、时间和预算的综合最优方案",
        "max_distance_from_start_km": 100,   # 【重构】候选集不限制距离
        "candidate_count": 30,
        "pref_match_boost": 1.0,
        "time_penalty_factor": 1.0,
        "max_travel_km_per_step": 20,
        "max_total_route_km": 60,
        "min_poi_count": 4,
        "two_opt_pref_weight": 0.5,
        "distance_weight": 0.7,
    }
}


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine公式计算两点间直线距离（米），乘以1.3作为实际距离估算"""
    R = 6371000  # 地球半径（米）
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
        math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c * 1.3  # 估算实际距离 = 直线 × 1.3


def estimate_travel_time(
    from_loc: Location, 
    to_loc: Location, 
    mode: str = "步行",
    city: Optional[str] = None
) -> Tuple[int, int, str]:
    """
    估算两点间的交通耗时、距离和实际交通方式
    【P1】优先查询OSRM真实距离矩阵
    【阶段一】多模式智能降级：步行超时自动切换更快的交通方式
    返回: (时间分钟, 距离米, 实际交通方式)
    """
    from backend.data.gaode_direction import select_best_transport
    return select_best_transport(from_loc, to_loc, mode, city or _current_planning_city)


def parse_time(time_str: str) -> datetime:
    """解析时间字符串 '09:00' → datetime对象（日期部分用今天）"""
    today = datetime.now().date()
    hour, minute = map(int, time_str.split(":"))
    return datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))


def _llm_generate_category_quota(raw_query: str, city: str, actual_categories: List[str], estimated_count: int) -> Optional[Dict[str, int]]:
    """
    调用LLM根据用户query动态生成类别配额。
    超时10秒，失败返回None。
    """
    if not raw_query or not raw_query.strip():
        return None
    try:
        from backend.core.llm_filter import get_client
        client = get_client()
        prompt = f"""你是一位旅行规划专家。请根据用户的旅行需求，为以下实际存在的POI类别分配推荐配额数量。

城市：{city}
实际存在的类别：{', '.join(actual_categories)}
预计总POI数量：约{estimated_count}个

用户query："{raw_query.strip()}"

要求：
1. 只输出纯JSON对象，不要任何解释、markdown代码块或其他文字
2. JSON键必须是上述实际存在的类别
3. 各配额之和应约等于{estimated_count}
4. 如果query没有明确偏向某类，按均衡分配
5. 如果query明确提到某类（如"美食""拍照""购物"），相应增加该类配额

示例输出格式：
{{"风景名胜": 4, "餐饮服务": 3, "购物服务": 2, "体育休闲服务": 1, "住宿服务": 0}}
"""
        import concurrent.futures
        def _call():
            resp = client.chat.completions.create(
                model="MiniMax-M3",
                messages=[
                    {"role": "system", "content": "你是一个只输出JSON的旅行规划配额助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            content = resp.choices[0].message.content.strip()
            # 【修复】MiniMax-M3 可能输出 <think>...</think> 包裹内容，先提取JSON部分
            if "</think>" in content:
                content = content.split("</think>", 1)[-1].strip()
            # 尝试提取JSON
            if content.startswith("```"):
                content = content.strip("`").strip()
                if content.lower().startswith("json"):
                    content = content[4:].strip()
            data = json.loads(content)
            # 过滤并归一化到实际类别
            result = {cat: int(data.get(cat, 0)) for cat in actual_categories}
            total = sum(result.values())
            if total == 0:
                return None
            # 如果总和与estimated_count差异太大，按比例缩放
            if total != estimated_count and estimated_count > 0:
                scale = estimated_count / total
                result = {cat: max(0, round(v * scale)) for cat, v in result.items()}
                # 微调确保总和正确
                diff = estimated_count - sum(result.values())
                while diff > 0:
                    for cat in sorted(result, key=lambda c: result[c], reverse=True):
                        if diff <= 0:
                            break
                        result[cat] += 1
                        diff -= 1
                while diff < 0:
                    for cat in sorted(result, key=lambda c: result[c]):
                        if diff >= 0 or result[cat] <= 0:
                            break
                        result[cat] -= 1
                        diff += 1
            return result

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_call)
        try:
            result = future.result(timeout=10)
        except concurrent.futures.TimeoutError:
            result = None
        finally:
            executor.shutdown(wait=False)
        return result
    except Exception as e:
        print(f"[CategoryQuota] LLM动态配额失败，回退到规则配额: {type(e).__name__}: {e}")
        return None


def compute_category_quota(user_pref, constraints, raw_query: Optional[str] = None):
    """根据用户偏好和约束计算各类别POI的推荐配额"""
    total_minutes = int((parse_time(constraints.end_time) - parse_time(constraints.start_time)).total_seconds() / 60)
    estimated_count = max(3, int(total_minutes / 70))
    actual_categories = ["风景名胜", "餐饮服务", "购物服务", "体育休闲服务", "住宿服务"]

    # 第一层：LLM动态配额（有raw_query时优先尝试）
    if raw_query and raw_query.strip():
        llm_quota = _llm_generate_category_quota(raw_query, constraints.city or "杭州", actual_categories, estimated_count)
        if llm_quota is not None:
            print(f"[CategoryQuota] LLM动态配额: {llm_quota}")
            return llm_quota

    # 第二层：规则动态配额（基于semantic_matcher关键词-类别相似度加权）
    if user_pref.theme_weights:
        from backend.core.semantic_matcher import semantic_matcher
        cat_weights = {cat: 0.0 for cat in actual_categories}
        for kw, weight in user_pref.theme_weights.items():
            for cat in actual_categories:
                sim = semantic_matcher.compute_similarity(kw, cat)
                cat_weights[cat] += weight * sim
        total_weight = sum(cat_weights.values())
        if total_weight > 0:
            cat_weights = {cat: v / total_weight for cat, v in cat_weights.items()}
            return {cat: max(0, round(estimated_count * ratio)) for cat, ratio in cat_weights.items()}

    # 第三层：回退到基础规则配额
    base_ratio = {
        "风景名胜": 0.40,
        "餐饮服务": 0.25,
        "购物服务": 0.15,
        "体育休闲服务": 0.10,
        "住宿服务": 0.10,
    }
    theme_str = str(user_pref.theme_weights).lower()
    if any(k in theme_str for k in ["美食", "吃", "火锅", "辣", "餐厅"]):
        base_ratio["餐饮服务"] += 0.10
        base_ratio["风景名胜"] -= 0.08
    if any(k in theme_str for k in ["文化", "历史", "博物馆", "古迹", "艺术"]):
        base_ratio["体育休闲服务"] += 0.12
        base_ratio["风景名胜"] -= 0.08
    if any(k in theme_str for k in ["购物", "逛街", "买", "商场"]):
        base_ratio["购物服务"] += 0.10
        base_ratio["风景名胜"] -= 0.08
    total = sum(base_ratio.values())
    base_ratio = {k: v / total for k, v in base_ratio.items()}
    return {cat: max(0, round(estimated_count * ratio)) for cat, ratio in base_ratio.items()}


def format_time(dt: datetime) -> str:
    """datetime → '09:30'"""
    return dt.strftime("%H:%M")


def is_within_open_hours(poi: POI, arrive_time: datetime, duration_min: int = 60) -> bool:
    """
    检查POI在到达时间和停留期间是否营业
    
    Args:
        poi: POI对象
        arrive_time: 到达时间
        duration_min: 预计停留时长（分钟），用于检查离开前是否已关门
    
    Returns:
        True 如果在营业时间内且离开时未关门（跨天营业除外）
    """
    if not poi.business_hours or poi.business_hours == "全天开放":
        return True
    
    try:
        bh = poi.business_hours.strip()
        if "-" in bh:
            open_str, close_str = bh.split("-", 1)
            open_hour, open_min = map(int, open_str.strip().split(":"))
            close_hour, close_min = map(int, close_str.strip().split(":"))
            
            arrive_total = arrive_time.hour * 60 + arrive_time.minute
            open_total = open_hour * 60 + open_min
            close_total = close_hour * 60 + close_min
            
            # 处理跨天营业（如 20:00-02:00）
            cross_day = close_total < open_total
            
            if cross_day:
                # 跨天营业：到达时间只要在开或关的一侧就算在营业时间内
                in_open = arrive_total >= open_total or arrive_total <= close_total
            else:
                in_open = open_total <= arrive_total <= close_total
            
            if not in_open:
                return False
            
            # 【增强】检查离开时是否已关门（非跨天营业时）
            if not cross_day and close_total > open_total:
                leave_total = arrive_total + duration_min
                if leave_total > close_total:
                    # 如果停留时间会超过关门时间，拒绝（除非只超一点，给15分钟缓冲）
                    if leave_total > close_total + 15:
                        return False
            
            return True
    except Exception:
        pass
    
    return True


def _compute_keyword_match_score(poi: POI, keywords: List[str]) -> float:
    """
    计算POI与关键词列表的语义匹配度 (0.0~1.0)
    【重构】使用本地 Embedding 模型进行语义相似度计算
    """
    if not keywords:
        return 0.0
    from backend.core.semantic_matcher import semantic_matcher
    keyword_weights = {kw: 1.0 for kw in keywords}
    return semantic_matcher.match_keywords_to_poi(keyword_weights, poi)


def compute_poi_marginal_value(
    poi: POI,
    pref_match: float,
    travel_time: int,
    dist_m: int,
    user_pref: UserPreference,
    budget: Optional[int],
    strategy: str = "balanced",
    policy: Optional[PlanningPolicy] = None,
    selected_categories: Optional[List[str]] = None,
    category_quota: Optional[Dict[str, int]] = None,
) -> float:
    """
    计算POI的边际价值 — 核心评分函数
    根据策略类型调整权重和惩罚，实现差异化选择
    【Day 3 调优】增加距离探索奖励，打破同质化
    【P0 重构】支持 LLM Policy 驱动的动态维度评分与系数化加成
    """
    # 策略配置：优先从 policy 获取，否则 fallback 到 STRATEGY_CONFIG
    if policy is not None:
        config = get_strategy_config(policy, strategy)
        if config is None:
            config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    else:
        config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    
    base_score = (poi.rating or 3.5) / 5.0
    weights = user_pref.poi_score_weights
    
    # 【策略差异化 Layer 2】根据策略调整各项权重
    pref_boost = config["pref_match_boost"]
    time_factor = config["time_penalty_factor"]
    
    # POI综合价值（策略影响权重分配）
    poi_value = (
        weights.get("experience", 0.3) * base_score +
        weights.get("preference_match", 0.3) * pref_match * pref_boost +
        weights.get("cost", 0.15) * (1 - (poi.price or 0) / max(1, budget or 500))
    )
    
    # 时间效率惩罚（策略影响惩罚强度）
    pace_penalty_map = {"悠闲": 0.5, "适中": 1.0, "紧凑": 1.5}
    base_penalty = travel_time * pace_penalty_map.get(user_pref.pace_preference, 1.0)
    time_penalty = base_penalty * time_factor
    
    marginal_value = poi_value * 100 - time_penalty
    
    # 【Day 3 核心调优】策略差异化距离奖励/惩罚
    dist_km = dist_m / 1000.0
    if strategy == "experience":
        # 深度体验：高匹配+远距离 = 探索奖励（鼓励去宋城、西溪湿地、灵隐寺）
        if dist_km > 5 and pref_match > 0.3:
            if policy is not None:
                exploration_factor = get_effective_coefficient(poi, "exploration_bonus_factor", policy)
                marginal_value += (dist_km - 5) * pref_match * 8 * exploration_factor
            else:
                marginal_value += (dist_km - 5) * pref_match * 8
        # 额外奖励高评分POI
        if base_score >= 0.9:
            marginal_value += 15
    elif strategy == "efficiency":
        # 高效省时：严格惩罚远距离，奖励超近距离
        if dist_km <= 1.5:
            marginal_value += 25  # 近距离奖励
        elif dist_km > 3:
            if policy is not None:
                distance_factor = get_effective_coefficient(poi, "distance_penalty_factor", policy)
                marginal_value -= (dist_km - 3) * 20 * distance_factor
            else:
                marginal_value -= (dist_km - 3) * 20  # 远距离强惩罚
    else:
        # 均衡推荐：轻微鼓励远距离高匹配POI，保持多样性
        if dist_km > 8 and pref_match > 0.4:
            if policy is not None:
                exploration_factor = get_effective_coefficient(poi, "exploration_bonus_factor", policy)
                marginal_value += (dist_km - 8) * pref_match * 5 * exploration_factor
            else:
                marginal_value += (dist_km - 8) * pref_match * 5
        # 【地理连续性奖励】近距离POI加分，超远距离减分
        if dist_km <= 3:
            marginal_value += 8
        elif dist_km > 6:
            if policy is not None:
                distance_factor = get_effective_coefficient(poi, "distance_penalty_factor", policy)
                marginal_value -= (dist_km - 6) * 5 * distance_factor
            else:
                marginal_value -= (dist_km - 6) * 5
    
    # ===== 个性化加成（Layer 5）=====
    # 【重构】统一使用语义匹配，删除硬编码主题引用
    effective_theme_weights = dict(user_pref.theme_weights)
    if policy is not None:
        policy_themes = policy.preference_space.get("theme_weights", {})
        if policy_themes:
            for dimension, weight in policy_themes.items():
                effective_theme_weights[dimension] = max(
                    effective_theme_weights.get(dimension, 0),
                    float(weight)
                )
    
    # 遍历所有有效关键词维度，使用语义匹配计算加分
    if effective_theme_weights:
        from backend.core.semantic_matcher import semantic_matcher
        poi_vec = semantic_matcher.get_poi_embedding(poi)
        for dimension, weight in effective_theme_weights.items():
            kw_vec = semantic_matcher.get_keyword_embedding(dimension)
            sim = float(np.dot(kw_vec, poi_vec))
            if sim > 0.3:
                marginal_value += weight * sim * 25
    
    # 排队意愿
    if user_pref.willingness_to_queue > 0.6 and any(t in (poi.tags or []) for t in ["人气", "排队"]):
        marginal_value += 15
    
    # 价格敏感度
    if user_pref.price_sensitivity > 0.7 and (poi.price or 0) == 0:
        marginal_value += 10
    
    # UGC情感分加成（范围约-15到+15分）
    if policy is not None:
        ugc_weight = get_effective_coefficient(poi, "ugc_sentiment_weight", policy)
        if poi.ugc_sentiment_score != 0:
            marginal_value += poi.ugc_sentiment_score * 15 * ugc_weight
    else:
        if poi.ugc_sentiment_score != 0:
            marginal_value += poi.ugc_sentiment_score * 15
    
    # UGC场景标签与人群匹配加成
    if user_pref.traveler_type and poi.ugc_scene_tags:
        scene_match_map = {
            "亲子": ["亲子", "儿童", "乐园", "科普", "互动"],
            "情侣": ["情侣", "浪漫", "约会", "夜景", "私密"],
            "朋友": ["聚会", "社交", "打卡", "热闹"],
            "独自": ["安静", "独处", "治愈", "小众"],
            "家庭": ["家庭", "老人", "无障碍", "宽敞"],
        }
        match_keywords = scene_match_map.get(user_pref.traveler_type, [])
        for tag in poi.ugc_scene_tags:
            if any(kw in tag for kw in match_keywords):
                if policy is not None:
                    scene_weight = get_effective_coefficient(poi, "scene_match_weight", policy)
                    marginal_value += 10 * scene_weight
                else:
                    marginal_value += 10
                break  # 只加一次
    
    # 【Phase Four】POI 多样性软惩罚
    if selected_categories and len(selected_categories) > 0:
        scenic_count = sum(1 for c in selected_categories if c == "风景名胜")
        scenic_ratio = scenic_count / len(selected_categories)
        # 当风景名胜占比超过40%时，新风景名胜POI得分降低（阈值从50%降至40%）
        if scenic_ratio > 0.4 and poi.category == "风景名胜":
            penalty = 1.0 + (scenic_ratio - 0.4) * 6.0  # 50%→1.6x, 60%→2.2x, 70%→2.8x
            marginal_value = marginal_value / penalty
        
        # 餐饮多样性奖励：如果餐饮比例过低，大幅提升餐饮POI得分
        food_count = sum(1 for c in selected_categories if c == "餐饮服务")
        food_ratio = food_count / len(selected_categories)
        if food_ratio < 0.2 and poi.category == "餐饮服务":
            marginal_value *= 1.5  # 从1.25提升到1.5
        
        # 购物/文化多样性奖励：如果只有风景名胜和餐饮，也鼓励其他类型
        other_count = len(selected_categories) - scenic_count - food_count
        other_ratio = other_count / len(selected_categories)
        if other_ratio < 0.15 and poi.category in ("购物服务", "科教文化服务"):
            marginal_value *= 1.3
    
    # 【第二层】类别配额软约束
    if category_quota and selected_categories is not None:
        cat = poi.category
        current_count = sum(1 for c in selected_categories if c == cat)
        target = category_quota.get(cat, 1)
        if current_count >= target + 2:
            return -float('inf')
        elif current_count >= target + 1:
            marginal_value *= 0.3
        elif current_count >= target:
            marginal_value *= 0.6
        elif current_count == 0 and target >= 1 and len(selected_categories) >= 2:
            marginal_value *= 1.35
        elif current_count < target * 0.5:
            marginal_value *= 1.15
    
    return marginal_value


def preference_guided_greedy(
    candidates: List[POI],
    user_pref: UserPreference,
    constraints: RouteConstraints,
    strategy: str = "balanced",
    policy: Optional[PlanningPolicy] = None,
    skeleton_pois: Optional[List[POI]] = None,
    raw_query: Optional[str] = None,
) -> List[PlanSegment]:
    """
    偏好引导的贪心路线构造
    根据策略类型使用不同的选择策略，实现路线差异化
    【P0 重构】支持 LLM Policy 驱动的动态策略参数
    """
    if policy is not None:
        config = get_strategy_config(policy, strategy)
        if config is None:
            config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    else:
        config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    segments: List[PlanSegment] = []
    category_quota = compute_category_quota(user_pref, constraints, raw_query=raw_query)
    remaining = [poi for poi in candidates]
    
    current_dt = parse_time(constraints.start_time)
    end_dt = parse_time(constraints.end_time)
    
    # 起点
    current_location = constraints.start_point or Location(lat=30.2596, lng=120.1460)
    total_cost = 0
    total_route_dist_m = 0  # 累计路线距离
    
    # 优先处理必去点
    must_visit_names = set(constraints.must_visit)
    avoid_keywords = set(constraints.avoid)
    
    # 【第四层】LLM骨架规划混合架构
    skeleton_names = set(p.name for p in (skeleton_pois or []))
    must_visit_names.update(skeleton_names)
    if skeleton_pois:
        skeleton_in_candidates = [p for p in candidates if p.name in skeleton_names]
        other_candidates = [p for p in candidates if p.name not in skeleton_names]
        candidates = skeleton_in_candidates + other_candidates
        remaining = [poi for poi in candidates]
    
    # policy 的 hard_constraint_overrides 可以补充 must_visit / avoid
    if policy is not None:
        hco = policy.hard_constraint_overrides
        if hco.get("must_visit"):
            must_visit_names.update(hco["must_visit"])
        if hco.get("avoid"):
            avoid_keywords.update(hco["avoid"])
    
    # 过滤掉要避免的POI（支持名称模糊匹配 + 类别匹配）
    def _should_avoid(poi) -> bool:
        if not avoid_keywords:
            return False
        name = poi.name or ""
        category = poi.category or ""
        sub_category = getattr(poi, 'sub_category', None) or ""
        for kw in avoid_keywords:
            kw = kw.strip()
            if not kw:
                continue
            # 精确名称匹配
            if name == kw:
                return True
            # 名称包含关键词（如"宾馆"匹配"浙江宾馆"）
            if kw in name:
                return True
            # 类别匹配（如"宾馆"匹配类别"住宿服务"）
            if kw in category or kw in sub_category:
                return True
            # 反向：关键词被类别包含（如"住宿服务"包含"住宿"）
            if category in kw or sub_category in kw:
                return True
        return False
    
    remaining = [p for p in remaining if not _should_avoid(p)]
    
    # 【策略差异化 Layer 2】每步允许的最大旅行距离（km）
    max_travel_km = config["max_travel_km_per_step"]
    max_total_route_km = config.get("max_total_route_km", 50)
    min_poi_count = config.get("min_poi_count", 3)
    
    while remaining and current_dt < end_dt:
        best_poi = None
        best_value = -float('inf')
        best_travel_time = 0
        best_dist = 0
        
        for poi in remaining:
            travel_time, dist_m, _ = estimate_travel_time(
                current_location, poi.location, constraints.transport_mode
            )
            
            # 【策略差异化】高效/均衡方案：限制每步距离，避免路线跨度失控
            if strategy in ("efficiency", "balanced") and dist_m > max_travel_km * 1000:
                continue
            
            # 【修复】总路线距离限制，防止跨越整个城市
            # 动态上限：POI越少时允许稍宽松，但始终有上限
            dynamic_limit = max_total_route_km * 1000 * (1 + max(0, min_poi_count - len(segments) - 1) * 0.25)
            if total_route_dist_m + dist_m > dynamic_limit:
                continue
            
            arrive_dt = current_dt + timedelta(minutes=travel_time)
            
            # 硬性约束检查（到达时营业 + 离开前未关门）
            effective_duration = poi.suggested_duration
            if strategy == "experience" and len(segments) < min_poi_count:
                effective_duration = int(poi.suggested_duration * 0.85)
            if not is_within_open_hours(poi, arrive_dt, duration_min=effective_duration):
                continue
            
            # 【修复】体验策略适度缩短停留时间，不代表逛满全场
            effective_duration = poi.suggested_duration
            if strategy == "experience" and len(segments) < min_poi_count:
                effective_duration = int(poi.suggested_duration * 0.85)
            
            finish_dt = arrive_dt + timedelta(minutes=effective_duration)
            # 【Phase Four】严格时间约束：仅POI严重不足时允许10分钟缓冲
            time_buffer = 10 if len(segments) < min_poi_count else 0
            if finish_dt > end_dt + timedelta(minutes=time_buffer):
                continue
            
            # 【阶段二】预算硬约束：加入新POI前检查累计花费
            if constraints.budget is not None and poi.price is not None:
                if total_cost + poi.price > constraints.budget * 0.9:
                    continue
            
            # 计算偏好匹配度
            pref_match = compute_preference_match(poi, user_pref.theme_weights)
            
            # 【策略差异化 + Phase Four】计算边际价值时传入策略类型、距离和已选类别
            selected_categories = [s.poi.category for s in segments]
            marginal_value = compute_poi_marginal_value(
                poi, pref_match, travel_time, dist_m, user_pref, constraints.budget, strategy, policy, selected_categories, category_quota
            )
            
            # 必去点强制加分
            if poi.name in must_visit_names:
                marginal_value += 200
            
            # 【Day 3 调优】体验策略：远距离POI如果时间不够后续安排，降分
            if strategy == "experience" and dist_m > 5000:
                remaining_time_after = int((end_dt - finish_dt).total_seconds() / 60)
                if remaining_time_after < 90:  # 剩余不足1.5小时，降分
                    marginal_value -= (90 - remaining_time_after) * 2
            
            # 【修复】当已走距离超过15km时，优先选择近距离POI以保持地理连续性
            if strategy == "experience" and total_route_dist_m > 15000 and dist_m > 3000:
                marginal_value -= (dist_m / 1000 - 3) * 10
            
            if marginal_value > best_value:
                best_value = marginal_value
                best_poi = poi
                best_travel_time = travel_time
                best_dist = dist_m
        
        if best_poi is None:
            break
        
        # 创建路线节点
        travel_time, dist_m, actual_mode = estimate_travel_time(
            current_location, best_poi.location, constraints.transport_mode
        )
        arrive_dt = current_dt + timedelta(minutes=travel_time)
        # 【修复】体验策略使用缩短后的停留时间
        seg_duration = best_poi.suggested_duration
        if strategy == "experience" and len(segments) < min_poi_count - 1:
            seg_duration = int(best_poi.suggested_duration * 0.85)
        leave_dt = arrive_dt + timedelta(minutes=seg_duration)
        
        # 记录选择原因
        reasons = record_selection_reason(best_poi, user_pref, format_time(arrive_dt))
        
        # 生成tips
        tips = None
        if best_poi.ugc_recent_warn:
            tips = f"⚠️ 网友提醒：{best_poi.ugc_recent_warn}"
        elif arrive_dt.hour < 10 and any(t in best_poi.tags for t in ["拍照", "摄影"]):
            tips = "上午光线柔和，适合拍照"
        elif best_poi.price == 0:
            tips = "免费开放"
        elif best_poi.rating and best_poi.rating >= 4.7:
            tips = f"评分{best_poi.rating}分，人气很高"
        
        segment = PlanSegment(
            poi=best_poi,
            arrive_time=format_time(arrive_dt),
            leave_time=format_time(leave_dt),
            duration=seg_duration,
            transport_to_next=f"{actual_mode}约{best_travel_time}分钟",
            transport_distance_m=best_dist,
            transport_mode=actual_mode,
            tips=tips,
            selection_reasons=reasons
        )
        segments.append(segment)
        
        # 更新状态
        current_dt = leave_dt
        current_location = best_poi.location
        total_route_dist_m += best_dist
        if best_poi.price:
            total_cost += best_poi.price
        remaining.remove(best_poi)
        must_visit_names.discard(best_poi.name)
    
    return segments


def compute_route_preference_score(
    segments: List[PlanSegment],
    user_pref: UserPreference
) -> float:
    """计算整条路线的偏好匹配总分"""
    total = 0.0
    for seg in segments:
        match = compute_preference_match(seg.poi, user_pref.theme_weights)
        crowd = compute_crowd_match(seg.poi.suitable_for, user_pref.traveler_type)
        total += match * 0.6 + crowd * 0.4
    return total


def preference_guided_two_opt(
    segments: List[PlanSegment],
    user_pref: UserPreference,
    transport_mode: str = "步行",
    strategy: str = "balanced",
    policy: Optional[PlanningPolicy] = None,
) -> List[PlanSegment]:
    """
    偏好引导的2-opt优化 【Day 3 修复】
    根据策略类型调整优化目标：
      - 体验优先：兼顾路程减少 + 偏好匹配度提升
      - 效率优先：只优化路程，不考虑偏好
      - 均衡：两者都考虑但不过度
    【P0 重构】支持 LLM Policy 驱动的动态策略参数
    
    2-opt核心：反转 segments[i:j+1] 这一段
      原边：(i-1)->i  和  j->(j+1)
      新边：(i-1)->j  和  i->(j+1)
    """
    if len(segments) < 3:
        return segments
    
    if policy is not None:
        config = get_strategy_config(policy, strategy)
        if config is None:
            config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    else:
        config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    improved = True
    max_iter = 50
    iteration = 0
    
    # 【策略差异化】从配置读取权重
    distance_weight = config["distance_weight"]
    preference_weight = config["two_opt_pref_weight"]
    
    # 起点位置
    start_location = Location(lat=30.2596, lng=120.1460)
    
    while improved and iteration < max_iter:
        improved = False
        iteration += 1
        
        # 【Day 3 修复】i从1开始，不交换第一个POI（保持必去点/起点不变）
        for i in range(1, len(segments)):
            for j in range(i + 1, len(segments)):
                # ========== 计算当前路径的距离 ==========
                old_dist = 0
                # 边 (i-1) -> i
                old_dist += estimate_travel_time(segments[i-1].poi.location, segments[i].poi.location, transport_mode)[1]
                
                # 边 j -> (j+1)
                if j + 1 < len(segments):
                    old_dist += estimate_travel_time(segments[j].poi.location, segments[j+1].poi.location, transport_mode)[1]
                
                # ========== 计算反转后的距离 ==========
                new_dist = 0
                # 边 (i-1) -> j
                new_dist += estimate_travel_time(segments[i-1].poi.location, segments[j].poi.location, transport_mode)[1]
                
                # 边 i -> (j+1)
                if j + 1 < len(segments):
                    new_dist += estimate_travel_time(segments[i].poi.location, segments[j+1].poi.location, transport_mode)[1]
                
                dist_delta = new_dist - old_dist
                
                # 【策略差异化】高效方案：只优化距离
                # 体验/均衡方案：同时考虑相邻POI的偏好协同度
                pref_delta = 0.0
                if strategy != "efficiency" and preference_weight > 0 and j + 1 < len(segments):
                    # 原相邻关系的偏好协同度
                    old_pref = (
                        compute_preference_match(segments[i-1].poi, user_pref.theme_weights) *
                        compute_preference_match(segments[i].poi, user_pref.theme_weights)
                    ) + (
                        compute_preference_match(segments[j].poi, user_pref.theme_weights) *
                        compute_preference_match(segments[j+1].poi, user_pref.theme_weights)
                    )
                    # 新相邻关系的偏好协同度
                    new_pref = (
                        compute_preference_match(segments[i-1].poi, user_pref.theme_weights) *
                        compute_preference_match(segments[j].poi, user_pref.theme_weights)
                    ) + (
                        compute_preference_match(segments[i].poi, user_pref.theme_weights) *
                        compute_preference_match(segments[j+1].poi, user_pref.theme_weights)
                    )
                    pref_delta = new_pref - old_pref
                
                # 综合判断是否交换
                # 距离减少是好事(dist_delta<0)，偏好协同提升也是好事(pref_delta>0)
                total_delta = (
                    distance_weight * dist_delta +
                    preference_weight * (-pref_delta * 5000)  # 偏好协同提升 → total_delta减小 → 更容易交换
                )
                
                # 根据策略设置不同的交换阈值
                threshold = -200 if strategy == "efficiency" else -100
                
                if total_delta < threshold:
                    segments[i:j + 1] = reversed(segments[i:j + 1])
                    _update_segment_times(segments, transport_mode)
                    improved = True
                    break
            if improved:
                break
    
    return segments


def _update_segment_times(segments: List[PlanSegment], transport_mode: str) -> datetime:
    """2-opt交换后，重新计算所有节点的时间
    返回: 最后离开时间的datetime对象（正确跟踪日期 rollover）
    """
    if not segments:
        return datetime.now()
    
    start_location = Location(lat=30.2596, lng=120.1460)
    current_dt = parse_time(segments[0].arrive_time) - timedelta(minutes=estimate_travel_time(
        start_location, segments[0].poi.location, transport_mode
    )[0])
    
    for i, seg in enumerate(segments):
        if i == 0:
            # 第一个segment：从起点出发，加上交通时间得到到达时间
            travel_time, dist_m, actual_mode = estimate_travel_time(
                start_location, seg.poi.location, transport_mode
            )
            current_dt += timedelta(minutes=travel_time)
            seg.transport_mode = actual_mode
        elif i > 0:
            travel_time, dist_m, actual_mode = estimate_travel_time(
                segments[i - 1].poi.location,
                seg.poi.location,
                transport_mode
            )
            current_dt += timedelta(minutes=travel_time)
            segments[i - 1].transport_to_next = f"{actual_mode}约{travel_time}分钟"
            segments[i - 1].transport_distance_m = dist_m
            segments[i - 1].transport_mode = actual_mode
        
        seg.arrive_time = format_time(current_dt)
        leave_dt = current_dt + timedelta(minutes=seg.poi.suggested_duration)
        seg.leave_time = format_time(leave_dt)
        current_dt = leave_dt
    
    # 最后一个segment没有下一站，清除其transport_distance_m避免重复计算
    if segments:
        segments[-1].transport_distance_m = 0
        segments[-1].transport_to_next = None
    
    return current_dt


def build_route_plan(
    segments: List[PlanSegment],
    theme: str,
    description: str,
    plan_id: str,
    end_time: Optional[str] = None,
    user_pref: Optional[UserPreference] = None,
) -> RoutePlan:
    """将路线节点列表构建为RoutePlan对象 【Day 3 增强推荐理由】【阶段三】支持超时检测与删减候选"""
    if not segments:
        return RoutePlan(
            plan_id=plan_id,
            theme=theme,
            description=description,
            total_time="0分钟",
            total_cost=0,
            poi_count=0,
            segments=[],
            overall_reasoning="未生成路线"
        )
    
    start_dt = parse_time(segments[0].arrive_time)
    end_dt = parse_time(segments[-1].leave_time)
    duration_min = int((end_dt - start_dt).total_seconds() / 60)
    hours = duration_min // 60
    mins = duration_min % 60
    total_time_str = f"{hours}小时{mins}分" if hours > 0 else f"{mins}分钟"
    
    total_cost = sum(seg.poi.price or 0 for seg in segments)
    
    # 【重构】生成有策略特色的整体推荐理由（基于用户关键词）
    poi_names = [seg.poi.name for seg in segments]
    categories = [seg.poi.category for seg in segments]
    
    # 统计特色
    has_far_poi = any(
        haversine_distance_m(30.2596, 120.1460, seg.poi.location.lat, seg.poi.location.lng) > 8000
        for seg in segments
    )
    free_count = sum(1 for seg in segments if (seg.poi.price or 0) == 0)
    food_count = sum(1 for seg in segments if seg.poi.category == "餐饮服务")
    
    # 【重构】基于用户关键词统计高匹配POI数量
    keyword_high_match_count = 0
    if user_pref and user_pref.theme_weights:
        from backend.core.semantic_matcher import semantic_matcher
        for seg in segments:
            match = semantic_matcher.match_keywords_to_poi(user_pref.theme_weights, seg.poi)
            if match > 0.6:
                keyword_high_match_count += 1
    
    if theme == "深度体验":
        reasoning = f"为你安排了{len(segments)}个精选地点"
        if has_far_poi:
            reasoning += "，特别包含远距离的高体验目的地"
        if keyword_high_match_count >= 2:
            reasoning += f"，其中{keyword_high_match_count}个地点高度匹配你的偏好"
        if food_count >= 2:
            reasoning += f"，{food_count}处美食体验满足味蕾"
        reasoning += f"。从{poi_names[0]}出发，一路深度探索至{poi_names[-1]}，"
        reasoning += "为了最好的体验，路程稍远也值得。"
    elif theme == "高效省时":
        reasoning = f"紧凑安排{len(segments)}个核心亮点"
        reasoning += f"，从{poi_names[0]}到{poi_names[-1]}一路顺畅不绕路"
        if free_count >= 3:
            reasoning += f"，其中{free_count}个免费景点帮你控制预算"
        reasoning += f"。总用时仅{total_time_str}，适合想高效打卡的你。"
    else:
        reasoning = f"均衡精选{len(segments)}个地点"
        reasoning += f"，从{poi_names[0]}到{poi_names[-1]}"
        if has_far_poi and keyword_high_match_count >= 2:
            reasoning += "，兼顾远距离亮点和你的偏好需求"
        elif has_far_poi:
            reasoning += "，既探索远方也兼顾效率"
        reasoning += f"。总用时{total_time_str}，是体验与效率的最佳平衡。"
    
    # 【阶段三】超时检测与删减候选
    is_overtime = False
    overtime_minutes = 0
    overtime_candidates = None
    if end_time and segments:
        planned_end = parse_time(segments[-1].leave_time)
        target_end = parse_time(end_time)
        if planned_end > target_end:
            is_overtime = True
            overtime_minutes = int((planned_end - target_end).total_seconds() / 60)
            # 生成可删减候选：跳过首尾，按（低匹配度 + 高时间）排序
            candidates_for_removal = []
            for idx, seg in enumerate(segments):
                if idx == 0 or idx == len(segments) - 1:
                    continue  # 保留首尾
                pref_match = 0.0
                if user_pref:
                    pref_match = compute_preference_match(seg.poi, user_pref.theme_weights)
                # 分数越高越容易删减：时间长 + 匹配度低
                removal_score = seg.poi.suggested_duration * (1.1 - pref_match)
                candidates_for_removal.append({
                    "name": seg.poi.name,
                    "category": seg.poi.category,
                    "duration": seg.poi.suggested_duration,
                    "match_score": round(pref_match, 2),
                    "removal_score": round(removal_score, 1),
                })
            candidates_for_removal.sort(key=lambda x: -x["removal_score"])
            overtime_candidates = candidates_for_removal

    return RoutePlan(
        plan_id=plan_id,
        theme=theme,
        description=description,
        total_time=total_time_str,
        total_cost=total_cost,
        poi_count=len(segments),
        segments=segments,
        overall_reasoning=reasoning,
        is_overtime=is_overtime,
        overtime_minutes=overtime_minutes,
        overtime_candidates=overtime_candidates,
    )


def filter_candidates_by_strategy(
    candidates: List[POI],
    strategy: str,
    start_location: Location,
    user_pref: Optional[UserPreference] = None,
    policy: Optional[PlanningPolicy] = None,
) -> List[POI]:
    """
    【重构】候选集不再按距离硬过滤，所有POI按语义匹配分数排序
    距离约束后移到路线构造阶段的边际价值计算中
    """
    if policy is not None:
        config = get_strategy_config(policy, strategy)
        if config is None:
            config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    else:
        config = STRATEGY_CONFIG.get(strategy, STRATEGY_CONFIG["balanced"])
    target_count = int(config.get("candidate_count", 30))
    
    # 【重构】不再按距离过滤，直接按 pre_score 排序取 Top-N
    candidates.sort(key=lambda p: p.pre_score, reverse=True)
    result = candidates[:target_count]
    
    # 确保 must_visit 在结果中
    if user_pref is not None:
        # 此逻辑由上层处理，这里仅做候选排序
        pass
    
    return result


def compute_route_similarity(plan1: RoutePlan, plan2: RoutePlan) -> float:
    """
    计算两条路线的Jaccard相似度（POI集合交集/并集）
    返回值 0~1，越高越相似
    """
    set1 = {seg.poi.name for seg in plan1.segments}
    set2 = {seg.poi.name for seg in plan2.segments}
    
    if not set1 or not set2:
        return 0.0
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def force_differentiate(
    plans: List[RoutePlan],
    all_candidates: List[POI],
    user_pref: Optional[UserPreference] = None,
    constraints: Optional[RouteConstraints] = None
) -> List[RoutePlan]:
    """
    【策略差异化 Layer 3】强制差异化 【Day 3 增强】
    如果两条路线相似度>50%，强制替换POI，直到相似度降下来
    """
    if len(plans) < 2:
        return plans
    
    # 【Day 3 修复】每对路线只处理一次，避免过度替换导致的振荡
    processed_pairs = set()
    # 收集所有计划中已使用的POI，用于全局唯一性奖励
    all_plan_names = set()
    for p in plans:
        all_plan_names.update(seg.poi.name for seg in p.segments)
    
    for i in range(len(plans)):
        for j in range(i + 1, len(plans)):
            pair_key = (i, j)
            if pair_key in processed_pairs:
                continue
            
            sim = compute_route_similarity(plans[i], plans[j])
            if sim > 0.45:
                plan_j_names = {seg.poi.name for seg in plans[j].segments}
                plan_i_names = {seg.poi.name for seg in plans[i].segments}
                
                if len(plans[j].segments) >= 3:
                    # 【Day 3 修复】优先替换交集中的POI，更有效地降低相似度
                    intersection = plan_j_names & plan_i_names
                    replace_candidates = []
                    for idx in range(1, len(plans[j].segments) - 1):
                        poi = plans[j].segments[idx].poi
                        # 交集中的POI优先级更高（priority=0），且按pre_score升序
                        priority = 0 if poi.name in intersection else 1
                        replace_candidates.append((priority, poi.pre_score, idx, poi))
                    
                    replace_candidates.sort(key=lambda x: (x[0], x[1]))
                    
                    # 【Day 3 修复】根据相似度动态决定替换数量
                    if sim > 0.7:
                        replace_count = min(3, len(replace_candidates))
                    elif sim > 0.55:
                        replace_count = 2
                    else:
                        replace_count = 1
                    replacements_done = 0
                    
                    for _, _, replace_idx, old_poi in replace_candidates:
                        if replacements_done >= replace_count:
                            break
                        
                        best_replacement = None
                        best_score = -float('inf')
                        
                        # 第一优先级：不在两个路线中且rating足够
                        for cand in all_candidates:
                            if cand.name in plan_j_names or cand.name in plan_i_names:
                                continue
                            if not cand.rating or cand.rating < 3.8:
                                continue
                            
                            score = cand.pre_score
                            if user_pref:
                                pref_match = compute_preference_match(cand, user_pref.theme_weights)
                                score += pref_match * 20
                            
                            # 【Day 3 修复】全局唯一性奖励：不在任何其他计划中的POI获得加分
                            if cand.name not in all_plan_names:
                                score += 30
                            else:
                                score -= 15  # 已在其他路线中的POI被惩罚
                            
                            if score > best_score:
                                best_score = score
                                best_replacement = cand
                        
                        if best_replacement is None:
                            # 第二优先级：仅不在plan_j中
                            for cand in all_candidates:
                                if cand.name in plan_j_names:
                                    continue
                                if not cand.rating or cand.rating < 3.5:
                                    continue
                                score = cand.pre_score
                                # 全局唯一性奖励
                                if cand.name not in all_plan_names:
                                    score += 20
                                if score > best_score:
                                    best_score = score
                                    best_replacement = cand
                        
                        if best_replacement:
                            # 保存旧POI，以便在时间超出时恢复
                            old_poi = plans[j].segments[replace_idx].poi
                            old_reasons = plans[j].segments[replace_idx].selection_reasons
                            
                            plans[j].segments[replace_idx].poi = best_replacement
                            plans[j].segments[replace_idx].selection_reasons = [
                                f"[规则] 与「{plans[i].theme}」路线差异化，推荐{best_replacement.name}带来独特体验"
                            ]
                            
                            # 统一使用步行模式，避免外部API调用
                            last_leave_dt = _update_segment_times(plans[j].segments, constraints.transport_mode if constraints else "步行")
                            
                            # 【P1修复】检查替换后是否严重超出时间限制
                            # 使用 _update_segment_times 返回的 datetime 对象，
                            # 可正确检测跨午夜的情况（parse_time 重新解析会丢失日期信息）
                            time_ok = True
                            if constraints and plans[j].segments:
                                end_dt = parse_time(constraints.end_time)
                                if last_leave_dt > end_dt:
                                    time_ok = False
                            
                            if time_ok:
                                plan_j_names.add(best_replacement.name)
                                all_plan_names.add(best_replacement.name)
                                replacements_done += 1
                            else:
                                # 超出时间限制，恢复旧POI
                                plans[j].segments[replace_idx].poi = old_poi
                                plans[j].segments[replace_idx].selection_reasons = old_reasons
                                _update_segment_times(plans[j].segments, constraints.transport_mode if constraints else "步行")
                    
                    plans[j] = build_route_plan(
                        plans[j].segments,
                        plans[j].theme,
                        plans[j].description,
                        plans[j].plan_id
                    )
                
                processed_pairs.add(pair_key)
    
    return plans


def generate_preference_variants(
    candidates: List[POI],
    user_pref: UserPreference,
    constraints: RouteConstraints,
    policy: Optional[PlanningPolicy] = None,
    skeleton_pois: Optional[List[POI]] = None,
    raw_query: Optional[str] = None,
) -> List[RoutePlan]:
    global _current_planning_city
    _current_planning_city = constraints.city or "杭州"
    """
    基于同一用户偏好，生成3个不同侧重的方案
    【核心升级】三层差异化策略：
      Layer 1: 候选集过滤差异化
      Layer 2: 选择策略差异化
      Layer 3: 路线结构强制差异化
    【P0 重构】支持 LLM Policy 驱动的动态策略参数
    """
    plans = []
    start_location = constraints.start_point or Location(lat=30.2596, lng=120.1460)
    
    # 【P0-fix】对候选POI进行去重/合并，避免灵隐寺+灵隐景区等重复
    candidates = _deduplicate_pois(candidates, constraints.city or "杭州")
    
    # 【Phase Four】过滤掉不适合旅游的类别
    excluded_categories = {"地名地址信息", "商务住宅信息"}
    candidates = [p for p in candidates if p.category not in excluded_categories]
    
    def _build_plan(cand, pref, cons, strategy_key, plan_id):
        """构建单条路线，带最小POI数量重试"""
        if policy is not None:
            strategy_cfg = get_strategy_config(policy, strategy_key)
            if strategy_cfg is None:
                config = STRATEGY_CONFIG[strategy_key]
                name = config["name"]
                description = config["description"]
            else:
                config = strategy_cfg
                # 从 policy.strategies 中查找 name 和 description
                name = strategy_key
                description = ""
                for s in policy.strategies:
                    if s.config is strategy_cfg:
                        name = s.name
                        description = s.description
                        break
                # fallback：如果找不到，用策略 key 映射
                if name == strategy_key:
                    key_map = {
                        "experience": ("深度体验", "专注你最感兴趣的偏好，允许绕路去高体验POI"),
                        "efficiency": ("高效省时", "严格短距离，用最短时间打卡最多亮点"),
                        "balanced": ("均衡推荐", "兼顾体验、时间和预算的综合最优方案"),
                    }
                    name, description = key_map.get(strategy_key, (strategy_key, ""))
        else:
            config = STRATEGY_CONFIG[strategy_key]
            name = config["name"]
            description = config["description"]
        seg = preference_guided_greedy(cand, pref, cons, strategy=strategy_key, policy=policy, skeleton_pois=skeleton_pois, raw_query=raw_query)
        
        # 如果POI不足，放宽限制重试
        retry = 0
        min_count = config.get("min_poi_count", 3)
        while len(seg) < min_count and retry < 2:
            retry += 1
            # 临时放宽策略参数
            original_max_step = config["max_travel_km_per_step"]
            original_max_total = config.get("max_total_route_km", 50)
            config["max_travel_km_per_step"] = original_max_step * (1 + retry * 0.5)
            config["max_total_route_km"] = original_max_total * (1 + retry * 0.3)
            seg = preference_guided_greedy(cand, pref, cons, strategy=strategy_key, policy=policy, skeleton_pois=skeleton_pois, raw_query=raw_query)
            # 恢复参数
            config["max_travel_km_per_step"] = original_max_step
            config["max_total_route_km"] = original_max_total
        
        seg = preference_guided_two_opt(seg, pref, cons.transport_mode, strategy=strategy_key, policy=policy)
        # 【修复】2-opt交换后重新计算时间和距离
        _update_segment_times(seg, cons.transport_mode)
        # 【P0-fix】强制插入午餐/晚餐时段的餐饮POI
        seg = _force_insert_meals(seg, candidates, cons, parse_time(cons.end_time), pref, policy)
        if seg:
            _update_segment_times(seg, cons.transport_mode)
            # 【Phase Four】强制插入餐饮后可能超时，裁剪超出结束时间的POI
            end_dt_obj = parse_time(cons.end_time)
            while len(seg) > 1 and parse_time(seg[-1].leave_time) > end_dt_obj + timedelta(minutes=10):
                # 【Phase Four】优先裁剪风景名胜，保留餐饮和文化/购物多样性
                if seg[-1].poi.category == "风景名胜":
                    seg.pop()
                else:
                    removed = False
                    for i in range(len(seg) - 2, 0, -1):
                        if seg[i].poi.category == "风景名胜":
                            seg.pop(i)
                            removed = True
                            break
                    if not removed:
                        seg.pop()
                if seg:
                    seg[-1].transport_to_next = None
                    seg[-1].transport_distance_m = 0
                    _update_segment_times(seg, cons.transport_mode)
            if seg:
                _update_segment_times(seg, cons.transport_mode)
        plan = build_route_plan(seg, name, description, plan_id, end_time=cons.end_time, user_pref=pref)
        plan.preference_weights_used = pref.poi_score_weights
        return plan
    
    # ========== 方案A：深度体验 ==========
    pref_a = copy.deepcopy(user_pref)
    if pref_a.theme_weights:
        pref_a.theme_weights = {k: min(1.0, v * 1.5) for k, v in pref_a.theme_weights.items()}
    cand_a = filter_candidates_by_strategy(candidates, "experience", start_location, pref_a, policy=policy)
    cand_a = _pre_filter_by_budget(cand_a, constraints.budget)
    constraints_a = copy.deepcopy(constraints)
    # 统一使用用户选择的交通方式（默认步行），避免无效的高德API调用
    plan_a = _build_plan(cand_a, pref_a, constraints_a, "experience", "plan_a")
    plans.append(plan_a)
    
    # ========== 方案B：高效省时 ==========
    pref_b = copy.deepcopy(user_pref)
    pref_b.pace_preference = "紧凑"
    pref_b.willingness_to_walk = 0.2
    cand_b = filter_candidates_by_strategy(candidates, "efficiency", start_location, pref_b, policy=policy)
    cand_b = _pre_filter_by_budget(cand_b, constraints.budget)
    plan_b = _build_plan(cand_b, pref_b, constraints, "efficiency", "plan_b")
    plans.append(plan_b)
    
    # ========== 方案C：均衡推荐 ==========
    cand_c = filter_candidates_by_strategy(candidates, "balanced", start_location, user_pref, policy=policy)
    cand_c = _pre_filter_by_budget(cand_c, constraints.budget)
    plan_c = _build_plan(cand_c, user_pref, constraints, "balanced", "plan_c")
    plans.append(plan_c)
    
    # Layer 3: 强制差异化（如果相似度过高）
    # print(f"[DEBUG3] plans[1] segments: {[s.poi.name for s in plans[1].segments]}")
    # print(f"[DEBUG] Before force_differentiate: sims = {compute_route_similarity(plans[0], plans[1]):.0%}, {compute_route_similarity(plans[0], plans[2]):.0%}, {compute_route_similarity(plans[1], plans[2]):.0%}")
    plans = force_differentiate(plans, candidates, user_pref, constraints)
    # print(f"[DEBUG] After force_differentiate: sims = {compute_route_similarity(plans[0], plans[1]):.0%}, {compute_route_similarity(plans[0], plans[2]):.0%}, {compute_route_similarity(plans[1], plans[2]):.0%}")
    
    return plans
