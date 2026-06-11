# -*- coding: utf-8 -*-
"""
路线规划业务编排服务
整合所有模块，提供高层API：
  1. 接收用户请求
  2. 解析偏好
  3. POI召回
  4. 调用路线规划引擎
  5. 生成解释
  6. 返回结果
"""

import json
import os
import uuid
from typing import List, Optional, Any, Dict

from backend.models.schemas import (
    PlanRequest, PlanResponse, RoutePlan, RouteConstraints,
    UserPreference, POI, RankedPOI, Location
)
from backend.core.preference import parse_preference_from_request
from backend.core.llm_parser import parse_preference_from_llm
from backend.core import route_engine
from backend.core.llm_reasoner import generate_poi_reasons, apply_llm_reasons_to_plan, generate_overall_reasoning
from backend.core.hybrid_filter import HybridPOIFilter
from backend.core.personalization import UserPersonalizationEngine
from backend.core.policy_generator import generate_planning_policy, PlanningPolicy
from backend.core.llm_reranker import rerank_and_fuse, POIRerankResult
from backend.data.loader import get_cached_pois
from backend.db.models import PlanCacheDAO


class RoutePlannerService:
    """路线规划服务（v2.0：支持用户画像融合与持久化缓存）"""
    
    def __init__(self):
        self._hot_cache: dict = {}  # 内存热点缓存（LRU，最近100条）
        self.hybrid_filter = HybridPOIFilter()
        self.personalization = UserPersonalizationEngine()
    
    @property
    def plan_cache(self):
        """兼容旧代码：返回内存缓存"""
        return self._hot_cache
    
    def _llm_skeleton_planning(self, candidate_pool: List[POI], user_pref: UserPreference, raw_query: str, city: str) -> List[POI]:
        """
        【第四层】LLM骨架规划：从候选池调用LLM选6-8个POI骨架
        用于指导后续路线规划，确保核心偏好被满足
        """
        if not raw_query or not raw_query.strip():
            return []
        if len(candidate_pool) < 10:
            return []
        
        try:
            from openai import OpenAI
            import json
            client = OpenAI(
                api_key=os.getenv("LLM_API_KEY", ""),
                base_url=os.getenv("LLM_BASE_URL", "")
            )
            model = os.getenv("LLM_MODEL_NAME", "")
            if not model:
                return []
            
            # 取Top-30候选作为输入，减少LLM上下文长度
            top_candidates = candidate_pool[:30]
            poi_list_text = "\n".join([
                f"{i+1}. {p.name} ({p.category}, 评分{p.rating or '未知'}, 价格¥{p.price or '未知'})"
                for i, p in enumerate(top_candidates)
            ])
            
            prompt = f"""你是一位资深旅行规划师。用户要去{city}旅行，需求是："{raw_query}"。

请从以下候选POI中，选出6-8个最符合用户需求的POI作为路线骨架（必须包含必去景点和代表性体验）。

要求：
1. 优先选择与用户query直接相关的POI
2. 类别尽量多样（不要全是风景名胜）
3. 必须包含至少1个餐饮POI
4. 按推荐顺序排列

候选POI：
{poi_list_text}

请严格按JSON数组输出，只输出POI名称：
["POI名称1", "POI名称2", ...]
"""
            
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "旅行规划专家，严格JSON输出，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                timeout=20,
            )
            content = resp.choices[0].message.content
            import re
            m = re.search(r'\[.*\]', content, re.DOTALL)
            if m:
                names = json.loads(m.group())
                name_set = set(names)
                skeleton = [p for p in candidate_pool if p.name in name_set]
                print(f"[Planner] LLM骨架规划选中 {len(skeleton)} 个POI: {[p.name for p in skeleton]}")
                return skeleton
        except Exception as e:
            print(f"[Planner] LLM骨架规划失败（非关键）: {e}")
        return []
    
    def _update_progress(self, task_id: Optional[str], step: str, progress: int):
        if task_id:
            from backend.db.models import TaskDAO
            TaskDAO.update_task(task_id, status='running', step=step, progress=progress)
    
    def plan(self, request: PlanRequest, user_id: Optional[int] = None, user_type: Optional[str] = None, task_id: Optional[str] = None) -> PlanResponse:
        """
        主规划入口（支持用户画像融合）
        """
        # 【热重载】强制重新加载核心模块，确保代码修改即时生效
        import importlib
        from backend.core import route_engine as _re_route, hybrid_filter as _re_hybrid, llm_filter as _re_llm, config as _re_config
        importlib.reload(_re_route)
        importlib.reload(_re_hybrid)
        importlib.reload(_re_llm)
        # 重新加载 .env 配置
        import dotenv
        dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'), override=True)
        importlib.reload(_re_config)
        
        request_id = str(uuid.uuid4())[:8]
        
        self._update_progress(task_id, 'parsing', 5)
        
        # 【P2-4】若用户有长期画像描述，拼接到 raw_query 中作为 LLM 上下文
        if user_id is not None:
            profile_row = self.personalization.load_profile(user_id, user_type or "registered")
            if profile_row and profile_row.get("profile_description"):
                desc = profile_row["profile_description"].strip()
                if desc:
                    original_query = request.raw_query or ""
                    request.raw_query = f"我的长期旅行偏好：{desc}。本次需求：{original_query}"
                    print(f"[Planner] 拼接画像描述到 raw_query，长度={len(request.raw_query)}")
        
        # Step 1: 解析用户偏好（有 raw_query 时优先走 LLM，失败 fallback 规则解析）
        current_pref = None
        if request.raw_query and request.raw_query.strip():
            current_pref = parse_preference_from_llm(
                raw_query=request.raw_query,
                preferences=request.preferences,
                travelers=request.travelers,
                pace=request.pace,
                budget=request.budget,
                must_visit=request.must_visit,
                avoid=request.avoid,
                transport_mode=request.transport_mode,
            )
        
        if current_pref is None:
            current_pref = parse_preference_from_request(
                preferences=request.preferences,
                travelers=request.travelers,
                pace=request.pace,
                budget=request.budget
            )
        
        # Step 1.5: 加载并融合用户长期画像
        historical_pref = None
        if user_id is not None:
            historical_pref = self.personalization.profile_to_preference(
                self.personalization.load_profile(user_id, user_type or "registered")
            )
        
        user_pref = self.personalization.fuse_preferences(current_pref, historical_pref)
        print(f"[Planner] 偏好融合: 当前请求 + {'历史画像' if historical_pref else '无历史'} → 融合完成")
        
        self._update_progress(task_id, 'parsing', 15)
        
        # Step 3: POI召回（缓存城市数据）
        all_pois = get_cached_pois(request.city)
        
        # Step 3.5: 动态抓取补充（根据用户自然语言查询按需抓取精准POI）
        # 【第三层】无 raw_query 但 preferences 非空时也触发
        should_dynamic_fetch = bool(request.raw_query and request.raw_query.strip())
        if not should_dynamic_fetch and request.preferences:
            should_dynamic_fetch = True
        
        if should_dynamic_fetch and len(all_pois) < 100:
            try:
                from backend.core.dynamic_fetch_planner import fetch_city_pois_dynamic
                # 【第三层】有 raw_query 时用 raw_query，否则用 preferences 拼接
                user_query = request.raw_query if (request.raw_query and request.raw_query.strip()) else "、".join(request.preferences)
                print(f"[Planner] 本地POI不足({len(all_pois)}个)，触发DynamicFetch")
                dynamic_pois = fetch_city_pois_dynamic(
                    city=request.city,
                    user_query=user_query,
                    avoid=request.avoid,
                    max_pois=80,
                    pages_per_query=3
                )
                if dynamic_pois:
                    existing_ids = {p.poi_id for p in all_pois}
                    added = 0
                    for dp in dynamic_pois:
                        if dp.poi_id not in existing_ids:
                            all_pois.append(dp)
                            existing_ids.add(dp.poi_id)
                            added += 1
                    print(f"[Planner] 动态抓取补充 {added} 个新POI，候选池共 {len(all_pois)} 个")
            except Exception as e:
                print(f"[Planner] 动态抓取失败（非关键）: {e}")
        elif should_dynamic_fetch:
            print(f"[Planner] 本地POI充足({len(all_pois)}个)，跳过DynamicFetch")
        
        self._update_progress(task_id, 'fetching', 25)
        
        # 计算城市中心坐标作为起点
        from backend.data.loader import get_city_center
        center = get_city_center(request.city)
        start_point = None
        if center:
            from backend.models.schemas import Location
            start_point = Location(lat=center["lat"], lng=center["lng"])
        
        # Step 2: 构建约束
        constraints = RouteConstraints(
            city=request.city,
            start_time=request.start_time,
            end_time=request.end_time,
            start_point=start_point,
            budget=request.budget,
            must_visit=request.must_visit,
            avoid=request.avoid,
            transport_mode=request.transport_mode
        )
        
        # Step 4: 混合POI筛选（自动选择规则/混合/LLM主导路径）
        candidates, strategy, filter_metadata = self.hybrid_filter.filter(
            all_pois, request, user_pref, constraints
        )
        print(f"[Planner] 筛选策略: {strategy.value}, 输入{filter_metadata['input_count']} → 输出{filter_metadata['output_count']}, 隐性需求: {filter_metadata.get('hidden_needs', 'N/A')}")
        
        self._update_progress(task_id, 'filtering', 45)
        
        # Step 4.5: 天气感知调整
        try:
            from backend.data.realtime import realtime_service
            weather = realtime_service.get_weather(request.city)
            if weather:
                candidates = realtime_service.apply_weather_boost(candidates, weather)
                print(f"[Planner] 天气感知: {weather.get('weather')}, {weather.get('temperature')}°C")
        except Exception as e:
            print(f"[Planner] 天气感知调整失败（非关键）: {e}")
        
        # Step 4.8 + 4.9: 【P2-2】Policy Generator 和 LLM Reranker 并行执行
        policy: Optional[PlanningPolicy] = None
        rerank_results: Dict[str, POIRerankResult] = {}
        candidate_pool: List[POI] = []
        
        if candidates:
            # 规则粗排：按 pre_score 排序取 Top-40 作为备选池
            sorted_candidates = sorted(candidates, key=lambda p: p.pre_score, reverse=True)
            candidate_pool = sorted_candidates[:40]
            
            if request.raw_query and request.raw_query.strip():
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                def _gen_policy():
                    try:
                        return generate_planning_policy(
                            raw_query=request.raw_query,
                            user_pref=user_pref,
                            candidates=candidates,
                            constraints=constraints,
                        )
                    except Exception as e:
                        print(f"[Planner] Policy generation failed: {e}")
                        return None
                
                def _do_rerank():
                    try:
                        top20 = candidate_pool[:20]
                        
                        # 计算距离映射
                        from backend.core.route_engine import haversine_distance_m
                        start_loc = constraints.start_point or Location(lat=30.2596, lng=120.1460)
                        distances_m: Dict[str, int] = {}
                        for p in top20:
                            if p.location:
                                distances_m[p.poi_id] = int(haversine_distance_m(
                                    start_loc.lat, start_loc.lng,
                                    p.location.lat, p.location.lng
                                ))
                        
                        # 规则粗排分数（pre_score 映射到 0-100）
                        max_pre = max((p.pre_score for p in top20), default=1.0)
                        min_pre = min((p.pre_score for p in top20), default=0.0)
                        pre_range = max_pre - min_pre if max_pre > min_pre else 1.0
                        rule_scores = {
                            p.name: (p.pre_score - min_pre) / pre_range * 100
                            for p in top20
                        }
                        
                        return rerank_and_fuse(
                            pois=top20,
                            rule_scores=rule_scores,
                            user_pref=user_pref,
                            raw_query=request.raw_query,
                            distances_m=distances_m,
                            rule_weight=0.6,
                            llm_weight=0.4,
                        )
                    except Exception as e:
                        print(f"[Planner] LLM rerank failed: {e}")
                        return {}
                
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_policy = executor.submit(_gen_policy)
                    future_rerank = executor.submit(_do_rerank)
                    
                    for future in as_completed([future_policy, future_rerank]):
                        try:
                            result = future.result(timeout=35)
                            if future == future_policy:
                                policy = result
                                if policy:
                                    print(f"[Planner] Policy generated: {policy.reasoning}")
                            else:
                                rerank_results = result
                                print(f"[Planner] LLM rerank completed for {len(rerank_results)} POIs")
                        except Exception as e:
                            print(f"[Planner] 并发任务失败: {e}")
        
        self._update_progress(task_id, 'planning', 65)
        
        # Step 4.95: 【第四层】LLM骨架规划（在筛选之后、路线规划之前）
        skeleton_pois = []
        if request.raw_query and request.raw_query.strip():
            try:
                skeleton_pois = self._llm_skeleton_planning(
                    candidate_pool=candidate_pool if candidate_pool else candidates[:30],
                    user_pref=user_pref,
                    raw_query=request.raw_query,
                    city=request.city,
                )
            except Exception as e:
                print(f"[Planner] 骨架规划调用失败（非关键）: {e}")
        
        self._update_progress(task_id, 'planning', 75)
        
        # Step 5: 偏好驱动路线规划（传入 policy 和 skeleton_pois）
        plans = route_engine.generate_preference_variants(candidates, user_pref, constraints, policy=policy, skeleton_pois=skeleton_pois, raw_query=request.raw_query)
        
        self._update_progress(task_id, 'reasoning', 85)
        
        # Step 6: LLM推荐理由生成（P1优化）
        # 只在有raw_query时启用LLM推荐理由，避免无意义调用
        # 使用并发加速，最多等待约8秒
        if request.raw_query and request.raw_query.strip():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def _gen_reasons(plan):
                try:
                    reasons = generate_poi_reasons(plan, user_pref, raw_query=request.raw_query)
                    if reasons:
                        apply_llm_reasons_to_plan(plan, reasons)
                    return True
                except Exception as e:
                    print(f"[Planner] LLM推荐理由生成失败，保持规则理由: {e}")
                    return False
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(_gen_reasons, p): p.theme for p in plans}
                for future in as_completed(futures):
                    theme = futures[future]
                    try:
                        future.result(timeout=10)
                    except Exception as e:
                        print(f"[Planner] {theme} 推荐理由超时或失败: {e}")
        
        self._update_progress(task_id, 'reasoning', 95)
        
        # Step 7: 缓存方案（内存热点 + SQLite 持久化）
        cache_entry = {
            "request": request,
            "user_pref": user_pref,
            "constraints": constraints,
            "candidates": candidates,
            "plans": plans,
            "filter_metadata": filter_metadata,
            "policy": policy,
            "rerank_results": rerank_results,
            "candidate_pool": candidate_pool,
        }
        self._hot_cache[request_id] = cache_entry
        
        # 控制热点缓存大小（LRU 简化版：超过100条清一半）
        if len(self._hot_cache) > 100:
            keys = list(self._hot_cache.keys())
            for k in keys[:50]:
                del self._hot_cache[k]
        
        # 持久化到 SQLite
        try:
            response_dict = PlanResponse(
                request_id=request_id,
                user_preference=user_pref,
                plans=plans,
                candidate_pois_count=len(candidates)
            ).model_dump()
            # 序列化候选池（精简字段以控制大小）
            candidate_pool_json = None
            if candidate_pool:
                slim_pool = []
                for p in candidate_pool:
                    slim = {
                        "poi_id": p.poi_id,
                        "name": p.name,
                        "city": p.city,
                        "category": p.category,
                        "rating": p.rating,
                        "price": p.price,
                        "location": p.location.model_dump() if p.location else None,
                        "pre_score": p.pre_score,
                    }
                    slim_pool.append(slim)
                candidate_pool_json = json.dumps(slim_pool, ensure_ascii=False)
            
            PlanCacheDAO.create(
                request_id=request_id,
                user_id=user_id,
                user_type=user_type,
                city=request.city,
                request_json=json.dumps(request.model_dump(), ensure_ascii=False),
                response_json=json.dumps(response_dict, ensure_ascii=False),
                filter_metadata_json=json.dumps(filter_metadata, ensure_ascii=False),
                candidate_pool_json=candidate_pool_json
            )
        except Exception as e:
            print(f"[Planner] 方案持久化失败（非关键）: {e}")
        
        # 构建 LLM 排序候选列表（供前端展示参考）
        ranked_candidates = None
        llm_rankings = filter_metadata.get("llm_rankings", [])
        if llm_rankings:
            from backend.core.route_engine import haversine_distance_m
            start_loc = constraints.start_point or Location(lat=30.2596, lng=120.1460)
            # 建立 poi_id -> POI 映射
            poi_map = {p.poi_id: p for p in all_pois}
            ranked = []
            for r in llm_rankings:
                pid = r.get("poi_id")
                poi = poi_map.get(pid)
                if not poi:
                    continue
                dist_km = None
                if poi.location:
                    dist_km = round(haversine_distance_m(
                        start_loc.lat, start_loc.lng,
                        poi.location.lat, poi.location.lng
                    ) / 1000, 1)
                ranked.append(RankedPOI(
                    poi_id=pid,
                    name=poi.name,
                    category=poi.category,
                    rating=poi.rating,
                    match_score=r.get("match_score", 50),
                    recommendation_reason=r.get("recommendation_reason", ""),
                    is_recommended=r.get("is_recommended", True),
                    distance_from_start_km=dist_km,
                    location=poi.location,
                ))
            # 按 match_score 降序排序
            ranked.sort(key=lambda x: x.match_score, reverse=True)
            ranked_candidates = ranked
            print(f"[Planner] LLM排序候选POI: {len(ranked_candidates)} 个")
        
        # 记录用户行为（历史表）
        if user_id is not None:
            try:
                self.personalization.record_plan_generated(
                    user_id=user_id, user_type=user_type or "anonymous",
                    request_id=request_id, request=request, response=None
                )
            except Exception as e:
                print(f"[Planner] 行为记录失败（非关键）: {e}")
        
        # 【P2-1】画像双轨更新：对话驱动（LLM增量）
        if user_id is not None and request.raw_query:
            try:
                self.personalization.dual_track_update(
                    user_id=user_id,
                    user_type=user_type or "anonymous",
                    raw_query=request.raw_query,
                    generated_plan=PlanResponse(
                        request_id=request_id,
                        user_preference=user_pref,
                        plans=plans,
                        candidate_pois_count=len(candidates)
                    ),
                    request_id=request_id
                )
            except Exception as e:
                print(f"[Planner] 画像双轨更新失败（非关键）: {e}")
        
        self._update_progress(task_id, 'completed', 100)
        
        return PlanResponse(
            request_id=request_id,
            user_preference=user_pref,
            plans=plans,
            candidate_pois_count=len(candidates),
            ranked_candidates=ranked_candidates
        )
    
    def _recall_pois(
        self,
        all_pois: List[POI],
        user_pref: UserPreference,
        constraints: RouteConstraints
    ) -> List[POI]:
        """
        偏好感知的POI召回
        返回足够大的候选池（最多30个），供三种策略分别过滤
        """
        from backend.core.preference import compute_preference_match, compute_crowd_match
        
        candidates = []
        avoid_names = set(constraints.avoid)
        
        for poi in all_pois:
            # 排除要避免的POI
            if poi.name in avoid_names:
                continue
            
            # 计算偏好匹配度
            pref_match = compute_preference_match(poi, user_pref.theme_weights)
            crowd_match = compute_crowd_match(poi.suitable_for, user_pref.traveler_type)
            
            # 综合预评分
            base_score = (poi.rating or 3.5) / 5.0
            pre_score = base_score * 0.3 + pref_match * 0.5 + crowd_match * 0.2
            
            poi.preference_match_score = pref_match
            poi.crowd_match_score = crowd_match
            poi.pre_score = pre_score
            
            candidates.append(poi)
        
        # 按预评分排序
        candidates.sort(key=lambda p: p.pre_score, reverse=True)
        
        # 【关键】保留Top-50候选，确保三种策略过滤后有足够POI
        # 体验策略要远距离POI（如宋城、西溪湿地），候选池必须够大
        final_candidates = candidates[:50]
        
        # 确保必去点在候选中
        must_names = set(constraints.must_visit)
        must_in_candidates = {p.name for p in final_candidates}
        for poi in all_pois:
            if poi.name in must_names and poi.name not in must_in_candidates:
                final_candidates.append(poi)
        
        return final_candidates
    
    def get_candidates(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        获取某次规划的备选池（Top-40 候选 POI + 精排结果）
        【P1】备选池API支持
        【修复】支持从数据库回退恢复（历史记录场景）
        """
        cached = self._hot_cache.get(request_id)
        
        # 回退到数据库
        if not cached:
            from backend.db.models import PlanCacheDAO
            db_entry = PlanCacheDAO.get(request_id)
            if db_entry and db_entry.get("candidate_pool_json"):
                try:
                    pool_data = json.loads(db_entry["candidate_pool_json"])
                    from backend.models.schemas import POI, Location
                    candidate_pool = []
                    for p in pool_data:
                        loc = None
                        if p.get("location"):
                            loc = Location(**p["location"])
                        poi = POI(
                            poi_id=p.get("poi_id", ""),
                            name=p["name"],
                            city=p.get("city", ""),
                            category=p["category"],
                            rating=p.get("rating"),
                            price=p.get("price"),
                            location=loc,
                        )
                        poi.pre_score = p.get("pre_score", 0.5)
                        candidate_pool.append(poi)
                    resp_data = json.loads(db_entry["response_json"])
                    cached = {
                        "candidate_pool": candidate_pool,
                        "plans": resp_data.get("plans", []),
                        "rerank_results": {},
                    }
                    self._hot_cache[request_id] = cached
                    print(f"[Planner] 从数据库恢复候选池: {request_id}, {len(candidate_pool)} 个POI")
                except Exception as e:
                    print(f"[Planner] 从数据库恢复候选池失败: {e}")
        
        if not cached:
            return None
        
        candidate_pool = cached.get("candidate_pool", [])
        rerank_results = cached.get("rerank_results", {})
        plans = cached.get("plans", [])
        
        # 收集所有已选中的 POI 名称
        plan_poi_names = set()
        for plan in plans:
            # plan 可能是 RoutePlan 对象或 dict
            if hasattr(plan, 'segments'):
                segments = plan.segments
            else:
                segments = plan.get("segments", [])
            for seg in segments:
                if hasattr(seg, 'poi'):
                    plan_poi_names.add(seg.poi.name)
                else:
                    plan_poi_names.add(seg.get("poi", {}).get("name", ""))
        
        # 构建返回列表
        candidates_info = []
        for poi in candidate_pool:
            rr = rerank_results.get(poi.name)
            info = {
                "poi": poi.model_dump(),
                "rule_score": round(rr.rule_score, 1) if rr else round(poi.pre_score * 100, 1),
                "llm_score": round(rr.llm_score, 1) if rr else None,
                "final_score": round(rr.final_score, 1) if rr else round(poi.pre_score * 100, 1),
                "recommendation_reason": rr.recommendation_reason if rr else None,
                "exclusion_reason": rr.exclusion_reason if rr else None,
                "is_in_plan": poi.name in plan_poi_names,
            }
            candidates_info.append(info)
        
        # 按 final_score 降序排序
        candidates_info.sort(key=lambda x: x["final_score"] or 0, reverse=True)
        
        return {
            "request_id": request_id,
            "candidates": candidates_info,
            "total": len(candidates_info),
        }
    
    def arrange_plan(
        self,
        request_id: str,
        add_poi_names: Optional[List[str]] = None,
        remove_poi_names: Optional[List[str]] = None,
        target_plan_id: str = "plan_a",
    ) -> Optional[PlanResponse]:
        """
        【P1】增量编排：在已有方案基础上局部插入/删除 POI，不重新全局规划。
        
        逻辑：
        1. 删除指定 POI
        2. 添加新 POI：找到距离最近的插入位置，插入后局部 2-opt
        3. 重新计算时间
        4. 检查约束
        """
        cached = self._hot_cache.get(request_id)
        if not cached:
            return None
        
        plans = cached.get("plans", [])
        if not plans:
            return None
        
        # 找到目标 plan
        target_plan = None
        for p in plans:
            if p.plan_id == target_plan_id:
                target_plan = p
                break
        if target_plan is None:
            target_plan = plans[0]
        
        # 复制 segments（避免修改原对象）
        import copy
        segments = [copy.deepcopy(s) for s in target_plan.segments]
        constraints = cached["constraints"]
        transport_mode = constraints.transport_mode
        
        # 1. 删除指定 POI
        if remove_poi_names:
            segments = [s for s in segments if s.poi.name not in remove_poi_names]
        
        # 2. 添加新 POI
        if add_poi_names:
            candidate_pool = cached.get("candidate_pool", [])
            candidates_by_name = {p.name: p for p in candidate_pool}
            # 也查 all_pois
            all_pois = cached.get("candidates", [])
            for p in all_pois:
                if p.name not in candidates_by_name:
                    candidates_by_name[p.name] = p
            
            for poi_name in add_poi_names:
                poi = candidates_by_name.get(poi_name)
                if not poi:
                    print(f"[Arrange] POI '{poi_name}' 不在候选池中，跳过")
                    continue
                if any(s.poi.name == poi_name for s in segments):
                    continue  # 已存在
                
                # 找到最近插入位置
                best_idx = self._find_nearest_insert_position(segments, poi, constraints)
                
                # 创建新 segment
                from backend.core.route_engine import format_time, parse_time, estimate_travel_time
                from datetime import timedelta
                
                # 简化：使用默认停留时间，transport 在后续统一计算
                new_seg = copy.deepcopy(segments[0]) if segments else None
                if new_seg:
                    new_seg.poi = poi
                    new_seg.arrive_time = "10:00"
                    new_seg.leave_time = "11:00"
                    new_seg.duration = poi.suggested_duration
                    new_seg.transport_to_next = None
                    new_seg.transport_distance_m = 0
                    new_seg.selection_reasons = [f"[用户] 从备选池手动添加"]
                else:
                    from backend.models.schemas import PlanSegment
                    new_seg = PlanSegment(
                        poi=poi,
                        arrive_time="10:00",
                        leave_time="11:00",
                        duration=poi.suggested_duration,
                        selection_reasons=["[用户] 从备选池手动添加"],
                    )
                
                segments.insert(best_idx, new_seg)
        
        # 3. 重新计算所有时间
        if segments:
            from backend.core.route_engine import _update_segment_times
            _update_segment_times(segments, transport_mode)
        
        # 4. 构建新 plan
        from backend.core.route_engine import build_route_plan
        new_plan = build_route_plan(
            segments,
            target_plan.theme,
            target_plan.description,
            target_plan.plan_id
        )
        new_plan.preference_weights_used = target_plan.preference_weights_used
        
        # 替换原 plan
        for i, p in enumerate(plans):
            if p.plan_id == target_plan.plan_id:
                plans[i] = new_plan
                break
        
        cached["plans"] = plans
        
        return PlanResponse(
            request_id=request_id,
            user_preference=cached["user_pref"],
            plans=plans,
            candidate_pois_count=len(cached.get("candidates", []))
        )
    
    def _find_nearest_insert_position(
        self,
        segments: List[Any],
        poi: POI,
        constraints: RouteConstraints
    ) -> int:
        """
        找到已有方案中距离新 POI 最近的插入位置。
        返回插入索引（插入到该索引之前）。
        """
        if not segments:
            return 0
        
        from backend.core.route_engine import haversine_distance_m
        
        best_idx = len(segments)
        best_dist = float('inf')
        
        for i, seg in enumerate(segments):
            if seg.poi.location and poi.location:
                dist = haversine_distance_m(
                    seg.poi.location.lat, seg.poi.location.lng,
                    poi.location.lat, poi.location.lng
                )
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i + 1  # 插入到该 POI 之后
        
        return best_idx
    
    def adjust_plan(
        self,
        request_id: str,
        mode: str = "replan",
        end_time: Optional[str] = None,
        budget: Optional[int] = None,
        add_poi: Optional[List[str]] = None,
        remove_poi: Optional[List[str]] = None,
        preference_shift: Optional[dict] = None
    ) -> Optional[PlanResponse]:
        """
        动态调整已有方案（支持持久化缓存回退）
        【P1】支持 mode="arrange" 增量编排
        """
        # 优先查内存热点缓存
        cached = self._hot_cache.get(request_id)
        
        # 回退到数据库
        if not cached:
            db_entry = PlanCacheDAO.get(request_id)
            if db_entry:
                try:
                    req_data = json.loads(db_entry["request_json"])
                    resp_data = json.loads(db_entry["response_json"])
                    # 简化重建：从 JSON 恢复关键字段
                    cached = {
                        "request": PlanRequest(**req_data),
                        "user_pref": UserPreference(**req_data.get("user_preference", {})),
                        "constraints": RouteConstraints(**req_data.get("constraints", {})),
                        "candidates": [],  # DB 不存 candidates，adjust 时不需要
                        "plans": resp_data.get("plans", []),
                        "filter_metadata": json.loads(db_entry.get("filter_metadata_json") or "{}"),
                    }
                    self._hot_cache[request_id] = cached
                except Exception as e:
                    print(f"[Planner] 从数据库恢复方案失败: {e}")
        
        if not cached:
            return None
        
        # 【P1】增量编排模式
        if mode == "arrange":
            return self.arrange_plan(
                request_id=request_id,
                add_poi_names=add_poi,
                remove_poi_names=remove_poi,
            )
        
        # 重新规划模式（原有逻辑）
        # 修改约束
        constraints = cached["constraints"]
        if end_time:
            constraints.end_time = end_time
        if budget is not None:
            constraints.budget = budget
        if add_poi:
            constraints.must_visit.extend(add_poi)
        if remove_poi:
            constraints.avoid.extend(remove_poi)
        
        # 微调偏好权重
        user_pref = cached["user_pref"]
        if preference_shift:
            for theme, delta in preference_shift.items():
                if theme in user_pref.theme_weights:
                    user_pref.theme_weights[theme] = min(
                        1.0, max(0.0, user_pref.theme_weights[theme] + delta)
                    )
        
        # 重新规划
        import importlib
        importlib.reload(route_engine)
        policy = cached.get("policy")
        plans = route_engine.generate_preference_variants(
            cached["candidates"], user_pref, constraints, policy=policy
        )
        
        cached["plans"] = plans
        cached["constraints"] = constraints
        cached["user_pref"] = user_pref
        
        return PlanResponse(
            request_id=request_id,
            user_preference=user_pref,
            plans=plans,
            candidate_pois_count=len(cached["candidates"])
        )


# 全局服务实例
planner_service = RoutePlannerService()
