# -*- coding: utf-8 -*-
"""
用户画像个性化引擎
负责：
  1. 加载用户长期画像
  2. 融合当前请求偏好与历史画像
  3. 基于行为演化画像（EMA 指数移动平均）
  4. 根据画像微调约束
"""

import json
from typing import Optional, Dict, List, Any

from backend.models.schemas import UserPreference, PlanRequest, RouteConstraints, POI
from backend.db.models import UserProfileDAO, UserHistoryDAO, UserFeedbackDAO
from backend.data.loader import get_cached_pois
from backend.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME


# 画像初始化 Prompt
PROFILE_INIT_PROMPT = """你是一位用户画像分析师。根据用户对自己旅行偏好的自然语言描述，提取结构化的长期画像信息。

请严格按以下 JSON 格式输出（只输出纯 JSON，不要任何解释）：
{
  "theme_weights": {"美食": 0.0~1.0, "拍照": ..., "文化": ..., "自然": ..., "购物": ..., "娱乐": ...},
  "traveler_type": "独自/情侣/亲子/朋友/家庭",
  "pace_preference": "紧凑/适中/悠闲",
  "budget_level": "经济/标准/高端",
  "price_sensitivity": 0.0~1.0,
  "willingness_to_queue": 0.0~1.0,
  "willingness_to_walk": 0.0~1.0
}

提取规则：
1. theme_weights 六个主题都必须有值。
   - 用户明确喜欢的主题（"我喜欢美食"）给 0.8~0.95
   - 用户明确不喜欢的主题（"我不爱购物"）给 0.05~0.15
   - 用户没提到的主题给 0.2~0.3
2. traveler_type：从描述中推断最常出行的群体
3. pace_preference：用户平时的旅行节奏倾向
4. budget_level：用户一贯的消费水平
5. price_sensitivity：用户对价格的敏感程度
6. willingness_to_queue：用户是否愿意排队（网红店/热门景点）
7. willingness_to_walk：用户是否喜欢步行/Citywalk
"""

PROFILE_DELTA_PROMPT = """你是一位用户画像分析师。根据用户本次旅行规划的对话（query + 系统生成的方案），提取用户对画像的"增量更新"。

只关注用户**明确表达或强烈暗示**的偏好变化，不要猜测。

请严格按以下 JSON 格式输出（只输出纯 JSON，不要任何解释）：
{
  "has_delta": true/false,
  "delta": {
    "theme_weights": {"新增或变化的维度": 0.0~1.0},
    "traveler_type": "独自/情侣/亲子/朋友/家庭（仅当用户明确提到时）",
    "pace_preference": "紧凑/适中/悠闲（仅当用户明确提到时）",
    "budget_level": "经济/标准/高端（仅当用户明确提到时）",
    "price_sensitivity": 0.0~1.0（仅当用户明确提到时）",
    "willingness_to_queue": 0.0~1.0（仅当用户明确提到时）",
    "willingness_to_walk": 0.0~1.0（仅当用户明确提到时）"
  },
  "reasoning": "简述提取到的增量和依据"
}

提取规则：
1. has_delta=false 当且仅当用户query和方案中没有任何新的偏好信息。
2. theme_weights 只包含**变化**的维度，不需要列出所有6个主题。
3. 数值含义：
   - 0.8~0.95 = 用户明确喜欢/强调
   - 0.05~0.15 = 用户明确不喜欢/排斥
   - 0.4~0.6 = 中性提及
4. 如果用户说"今天想换个风格""这次不一样"，has_delta=true，delta中记录临时偏好。
5. 不要输出任何解释文字，只输出纯 JSON。
"""


class UserPersonalizationEngine:
    """用户画像个性化引擎"""
    
    def __init__(self):
        self.fusion_alpha = 0.7  # 当前请求权重
        self.ema_gamma_new = 0.5  # 新用户学习率
        self.ema_gamma_old = 0.1  # 老用户学习率
    
    # ========================================================================
    # 画像加载
    # ========================================================================
    
    def load_profile(self, user_id: Optional[int], user_type: str = "registered") -> Optional[Dict[str, Any]]:
        """加载用户画像数据"""
        if user_id is None:
            return None
        return UserProfileDAO.get(user_id, user_type)
    
    def profile_to_preference(self, profile: Optional[Dict[str, Any]]) -> Optional[UserPreference]:
        """将数据库画像转换为 UserPreference 对象"""
        if not profile:
            return None
        
        theme_weights = {}
        try:
            theme_weights = json.loads(profile.get("theme_weights_json", "{}"))
        except json.JSONDecodeError:
            theme_weights = {}
        
        # 确保基础标签存在
        for tag in ["美食", "拍照", "文化", "自然", "购物", "娱乐"]:
            if tag not in theme_weights:
                theme_weights[tag] = 0.25
        
        return UserPreference(
            theme_weights=theme_weights,
            traveler_type=profile.get("traveler_type", "独自"),
            pace_preference=profile.get("pace_preference", "适中"),
            budget_level=profile.get("budget_level"),
            price_sensitivity=profile.get("price_sensitivity", 0.5),
            willingness_to_queue=profile.get("willingness_to_queue", 0.5),
            willingness_to_walk=profile.get("willingness_to_walk", 0.5),
        )
    
    # ========================================================================
    # 偏好融合
    # ========================================================================
    
    def fuse_preferences(
        self,
        current: UserPreference,
        historical: Optional[UserPreference]
    ) -> UserPreference:
        """
        融合当前请求偏好与历史画像
        公式: fused = alpha * current + (1 - alpha) * historical
        """
        if not historical:
            return current
        
        alpha = self.fusion_alpha
        
        # 融合主题权重
        fused_themes = {}
        all_themes = set(current.theme_weights.keys()) | set(historical.theme_weights.keys())
        for theme in all_themes:
            curr = current.theme_weights.get(theme, 0.25)
            hist = historical.theme_weights.get(theme, 0.25)
            fused_themes[theme] = round(alpha * curr + (1 - alpha) * hist, 4)
        
        # 融合标量偏好
        def _fuse_scalar(curr, hist):
            if hist is None:
                return curr
            return round(alpha * curr + (1 - alpha) * hist, 4)
        
        return UserPreference(
            theme_weights=fused_themes,
            traveler_type=current.traveler_type or historical.traveler_type,
            pace_preference=current.pace_preference or historical.pace_preference,
            budget_level=current.budget_level or historical.budget_level,
            price_sensitivity=_fuse_scalar(current.price_sensitivity, historical.price_sensitivity),
            willingness_to_queue=_fuse_scalar(current.willingness_to_queue, historical.willingness_to_queue),
            willingness_to_walk=_fuse_scalar(current.willingness_to_walk, historical.willingness_to_walk),
        )
    
    # ========================================================================
    # 画像演化
    # ========================================================================
    
    def evolve_profile(
        self,
        user_id: int,
        user_type: str,
        selected_plan_theme: Optional[str] = None,
        selected_poi_names: Optional[List[str]] = None,
        city: Optional[str] = None,
        budget: Optional[int] = None
    ):
        """
        基于用户行为更新长期画像（EMA 演化）
        在 plan() 完成后或用户选择方案后调用
        """
        profile = self.load_profile(user_id, user_type)
        if not profile:
            return
        
        # 确定学习率 gamma
        plans_generated = profile.get("total_plans_generated", 0)
        gamma = self.ema_gamma_old if plans_generated > 5 else self.ema_gamma_new
        
        # 加载当前权重
        current_weights = {}
        try:
            current_weights = json.loads(profile.get("theme_weights_json", "{}"))
        except json.JSONDecodeError:
            current_weights = {}
        
        # 确保基础标签存在
        for tag in ["美食", "拍照", "文化", "自然", "购物", "娱乐"]:
            if tag not in current_weights:
                current_weights[tag] = 0.25
        
        # 1. 隐式学习：方案主题偏好
        if selected_plan_theme:
            theme_boost_map = {
                "深度体验": {"体验偏好": 0.15, "文化": 0.05, "自然": 0.05},
                "高效省时": {"效率偏好": 0.15, "紧凑": 0.05},
                "均衡推荐": {"均衡": 0.1},
            }
            boosts = theme_boost_map.get(selected_plan_theme, {})
            for key, delta in boosts.items():
                current_weights[key] = current_weights.get(key, 0.5) + gamma * delta
        
        # 2. 隐式学习：POI 级别标签
        if selected_poi_names and city:
            pois = get_cached_pois(city)
            poi_map = {p.name: p for p in pois}
            for poi_name in selected_poi_names:
                poi = poi_map.get(poi_name)
                if poi and poi.tags:
                    for tag in poi.tags:
                        current_weights[tag] = current_weights.get(tag, 0.25) + gamma * 0.05
        
        # 3. 显式反馈
        feedbacks = UserFeedbackDAO.get_by_user(user_id, user_type)
        for fb in feedbacks:
            poi_name = fb["poi_name"]
            fb_type = fb["feedback_type"]
            delta = gamma * 0.1 if fb_type == "like" else -gamma * 0.1
            
            # 找到该 POI 的标签来传播反馈
            if city:
                pois = get_cached_pois(city)
                for poi in pois:
                    if poi.name == poi_name and poi.tags:
                        for tag in poi.tags:
                            current_weights[tag] = current_weights.get(tag, 0.25) + delta
                        break
        
        # 4. 归一化到 [0.05, 1.0]
        for k in list(current_weights.keys()):
            current_weights[k] = max(0.05, min(1.0, current_weights[k]))
        
        # 5. 更新数据库
        update_fields = {
            "theme_weights_json": json.dumps(current_weights, ensure_ascii=False),
            "total_plans_generated": plans_generated + 1,
        }
        
        if selected_plan_theme:
            update_fields["total_plans_selected"] = profile.get("total_plans_selected", 0) + 1
            # 更新最常选择主题
            history = UserHistoryDAO.get_by_user(user_id, user_type, limit=100)
            theme_counts = {}
            for h in history:
                t = h.get("selected_plan_theme")
                if t:
                    theme_counts[t] = theme_counts.get(t, 0) + 1
            if theme_counts:
                most_common = max(theme_counts, key=theme_counts.get)
                update_fields["most_selected_theme"] = most_common
        
        if budget is not None:
            old_avg = profile.get("avg_budget")
            if old_avg:
                new_avg = old_avg * (1 - gamma) + budget * gamma
            else:
                new_avg = budget
            update_fields["avg_budget"] = round(new_avg, 2)
        
        UserProfileDAO.update_stats(user_id, user_type, **update_fields)
    
    # ========================================================================
    # 画像微调约束
    # ========================================================================
    
    def adjust_constraints_by_profile(
        self,
        constraints: RouteConstraints,
        profile: Optional[Dict[str, Any]]
    ) -> RouteConstraints:
        """
        根据用户画像微调约束条件
        例如：历史偏好高效 → 缩小 max_total_route_km
        """
        if not profile:
            return constraints
        
        # 解析画像中的权重
        weights = {}
        try:
            weights = json.loads(profile.get("theme_weights_json", "{}"))
        except json.JSONDecodeError:
            pass
        
        # 根据效率偏好微调
        efficiency_pref = weights.get("效率偏好", 0.0)
        if efficiency_pref > 0.6:
            # 用户偏好高效，压缩总路线距离（如果存在的话）
            # 注意：RouteConstraints 目前没有这个字段，这里是示例
            pass
        
        return constraints
    
    # ========================================================================
    # 工具方法
    # ========================================================================
    
    def record_plan_generated(
        self,
        user_id: Optional[int],
        user_type: str,
        request_id: str,
        request: PlanRequest,
        response: Any
    ):
        """记录一次规划行为到历史表"""
        if user_id is None:
            return
        
        UserHistoryDAO.create(
            user_id=user_id,
            user_type=user_type,
            request_id=request_id,
            city=request.city,
            raw_query=request.raw_query,
        )
    
    def record_plan_selected(
        self,
        request_id: str,
        selected_plan_theme: str,
        selected_poi_names: List[str],
        total_cost: Optional[int] = None,
        total_time: Optional[str] = None
    ):
        """记录用户选择了哪个方案"""
        UserHistoryDAO.select_plan(
            request_id=request_id,
            selected_plan_theme=selected_plan_theme,
            selected_poi_names=selected_poi_names,
            total_cost=total_cost,
            total_time=total_time
        )


    # ========================================================================
    # 画像初始化（新增：从用户自然语言文本生成初始画像）
    # ========================================================================

    def init_profile_from_text(self, profile_text: str) -> Optional[UserPreference]:
        """
        从用户输入的画像描述文本（如"我喜欢美食和拍照，不喜欢排队"）生成初始画像。
        返回 UserPreference 对象，可存入数据库作为用户的长期画像。
        """
        if not profile_text or not profile_text.strip():
            return None
        if not LLM_API_KEY:
            print("[ProfileInit] LLM_API_KEY 未配置，无法初始化画像")
            return None

        try:
            from openai import OpenAI
            client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

            response = client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=[
                    {"role": "system", "content": PROFILE_INIT_PROMPT},
                    {"role": "user", "content": f"用户的旅行偏好描述：{profile_text}"},
                ],
                temperature=0.3,
                timeout=30,
            )

            content = response.choices[0].message.content
            if not content:
                return None

            # 清理 markdown 和 think 标签
            clean = content.strip()
            # 去除 <think>...</think>
            if "<think>" in clean and "</think>" in clean:
                clean = clean.split("</think>")[-1].strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            elif clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            parsed = json.loads(clean)
            return self._parsed_to_user_preference(parsed)

        except Exception as e:
            print(f"[ProfileInit] LLM画像初始化失败: {e}")
            return None

    @staticmethod
    def _parsed_to_user_preference(parsed: dict) -> UserPreference:
        """将LLM返回的JSON转换为UserPreference对象"""
        all_themes = ["美食", "拍照", "文化", "自然", "购物", "娱乐"]
        theme_weights = {}
        llm_themes = parsed.get("theme_weights", {})
        for theme in all_themes:
            if theme in llm_themes:
                theme_weights[theme] = max(0.0, min(1.0, float(llm_themes[theme])))
            else:
                theme_weights[theme] = 0.25

        traveler_type = parsed.get("traveler_type", "独自")
        if traveler_type not in ("独自", "情侣", "亲子", "朋友", "家庭"):
            traveler_type = "独自"

        pace = parsed.get("pace_preference", "适中")
        if pace not in ("紧凑", "适中", "悠闲"):
            pace = "适中"

        budget_level = parsed.get("budget_level")
        if budget_level not in ("经济", "标准", "高端"):
            budget_level = "标准"

        def _clamp(v):
            return max(0.0, min(1.0, float(v))) if v is not None else 0.5

        return UserPreference(
            theme_weights=theme_weights,
            traveler_type=traveler_type,
            pace_preference=pace,
            budget_level=budget_level,
            price_sensitivity=_clamp(parsed.get("price_sensitivity")),
            willingness_to_queue=_clamp(parsed.get("willingness_to_queue")),
            willingness_to_walk=_clamp(parsed.get("willingness_to_walk")),
        )

    def save_profile_to_db(
        self,
        user_id: int,
        user_type: str,
        preference: UserPreference,
        source: str = "user_manual",
        delta: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ):
        """将UserPreference持久化到数据库画像表，并记录版本历史"""
        update_fields = {
            "theme_weights_json": json.dumps(preference.theme_weights, ensure_ascii=False),
            "traveler_type": preference.traveler_type,
            "pace_preference": preference.pace_preference,
            "budget_level": preference.budget_level,
            "price_sensitivity": preference.price_sensitivity,
            "willingness_to_queue": preference.willingness_to_queue,
            "willingness_to_walk": preference.willingness_to_walk,
        }
        UserProfileDAO.update_stats(user_id, user_type, **update_fields)

        # 记录版本历史
        from backend.db.models import ProfileVersionDAO
        snapshot = {k: v for k, v in update_fields.items()}
        snapshot["theme_weights_json"] = json.loads(snapshot["theme_weights_json"])  # 存为dict便于阅读
        ProfileVersionDAO.create(
            user_id=user_id,
            user_type=user_type,
            source=source,
            delta=delta or {},
            profile_snapshot=snapshot,
            request_id=request_id
        )
        print(f"[ProfileInit] 画像已保存到数据库 (user_id={user_id}, source={source})")

    # ========================================================================
    # 画像增量提取（对话驱动）
    # ========================================================================

    def extract_profile_delta(
        self,
        raw_query: str,
        generated_plan: Optional[Any] = None,
        user_pref: Optional[UserPreference] = None
    ) -> Optional[Dict[str, Any]]:
        """
        调用 LLM 从本次规划对话中提取画像增量。
        返回 delta dict 或 None（无变化）。
        """
        if not raw_query or not raw_query.strip():
            return None
        if not LLM_API_KEY:
            return None

        plan_summary = ""
        if generated_plan and hasattr(generated_plan, 'plans'):
            themes = [p.theme for p in generated_plan.plans]
            plan_summary = f"生成方案主题: {themes}"

        pref_summary = ""
        if user_pref:
            pref_summary = user_pref.model_dump_json(indent=2, exclude_none=True)

        user_context = f"""用户原始query：{raw_query}

当前融合画像：
{pref_summary}

{plan_summary}

请提取本次对话中的画像增量。"""

        try:
            from openai import OpenAI
            client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

            response = client.chat.completions.create(
                model=LLM_MODEL_NAME,
                messages=[
                    {"role": "system", "content": PROFILE_DELTA_PROMPT},
                    {"role": "user", "content": user_context},
                ],
                temperature=0.3,
                timeout=15,
            )

            content = response.choices[0].message.content
            if not content:
                return None

            clean = content.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            elif clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            parsed = json.loads(clean)
            if not parsed.get("has_delta"):
                return None
            return parsed.get("delta")

        except Exception as e:
            print(f"[ProfileDelta] 增量提取失败: {e}")
            return None

    def apply_delta_to_profile(
        self,
        user_id: int,
        user_type: str,
        delta: Dict[str, Any],
        gamma: float = 0.3
    ) -> Optional[UserPreference]:
        """
        将增量应用到现有画像（平滑融合，gamma为学习率）。
        返回更新后的 UserPreference。
        """
        profile = self.load_profile(user_id, user_type)
        if not profile:
            return None

        current_pref = self.profile_to_preference(profile)
        if not current_pref:
            return None

        # 1. 融合 theme_weights
        delta_weights = delta.get("theme_weights", {})
        if delta_weights:
            for theme, new_val in delta_weights.items():
                old_val = current_pref.theme_weights.get(theme, 0.25)
                current_pref.theme_weights[theme] = round(
                    (1 - gamma) * old_val + gamma * max(0.0, min(1.0, float(new_val))), 4
                )

        # 2. 覆盖标量字段（仅当delta中明确提供时）
        scalar_fields = [
            "traveler_type", "pace_preference", "budget_level",
            "price_sensitivity", "willingness_to_queue", "willingness_to_walk"
        ]
        for field in scalar_fields:
            if field in delta and delta[field] is not None:
                setattr(current_pref, field, delta[field])

        # 值域裁剪
        for field in ["price_sensitivity", "willingness_to_queue", "willingness_to_walk"]:
            val = getattr(current_pref, field)
            if val is not None:
                setattr(current_pref, field, max(0.0, min(1.0, float(val))))

        pace = current_pref.pace_preference
        if pace not in ("紧凑", "适中", "悠闲"):
            current_pref.pace_preference = "适中"

        budget = current_pref.budget_level
        if budget not in ("经济", "标准", "高端"):
            current_pref.budget_level = "标准"

        return current_pref

    def dual_track_update(
        self,
        user_id: int,
        user_type: str,
        raw_query: Optional[str] = None,
        generated_plan: Optional[Any] = None,
        selected_plan_theme: Optional[str] = None,
        selected_poi_names: Optional[List[str]] = None,
        city: Optional[str] = None,
        budget: Optional[int] = None,
        request_id: Optional[str] = None
    ):
        """
        画像双轨更新：行为驱动（EMA）+ 对话驱动（LLM增量）。
        在每次规划请求完成后调用。
        """
        # Track 1: 行为驱动 EMA
        if selected_plan_theme or selected_poi_names:
            try:
                self.evolve_profile(
                    user_id=user_id,
                    user_type=user_type,
                    selected_plan_theme=selected_plan_theme,
                    selected_poi_names=selected_poi_names,
                    city=city,
                    budget=budget
                )
                print(f"[DualTrack] 行为驱动更新完成 (user_id={user_id})")
            except Exception as e:
                print(f"[DualTrack] 行为驱动更新失败: {e}")

        # Track 2: 对话驱动 LLM增量
        if raw_query:
            try:
                delta = self.extract_profile_delta(
                    raw_query=raw_query,
                    generated_plan=generated_plan,
                    user_pref=self.profile_to_preference(self.load_profile(user_id, user_type))
                )
                if delta:
                    updated_pref = self.apply_delta_to_profile(
                        user_id=user_id,
                        user_type=user_type,
                        delta=delta,
                        gamma=0.3
                    )
                    if updated_pref:
                        self.save_profile_to_db(
                            user_id=user_id,
                            user_type=user_type,
                            preference=updated_pref,
                            source="llm_delta",
                            delta=delta,
                            request_id=request_id
                        )
                        print(f"[DualTrack] 对话驱动更新完成 (user_id={user_id}), delta={delta}")
                else:
                    print(f"[DualTrack] 对话驱动无增量 (user_id={user_id})")
            except Exception as e:
                print(f"[DualTrack] 对话驱动更新失败: {e}")
