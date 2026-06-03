# -*- coding: utf-8 -*-
"""
数据模型定义 (Pydantic)
所有API的输入输出数据结构
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Location(BaseModel):
    """经纬度坐标"""
    lat: float = Field(..., description="纬度", ge=-90, le=90)
    lng: float = Field(..., description="经度", ge=-180, le=180)


class POI(BaseModel):
    """POI数据模型"""
    poi_id: str = Field(..., description="POI唯一标识")
    name: str = Field(..., description="POI名称")
    city: str = Field(..., description="所属城市")
    district: Optional[str] = Field(None, description="区县")
    category: str = Field(..., description="一级分类")
    sub_category: Optional[str] = Field(None, description="二级分类")
    address: Optional[str] = Field(None, description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(None, description="电话")
    rating: Optional[float] = Field(None, description="评分 0-5", ge=0, le=5)
    price: Optional[int] = Field(None, description="人均消费/门票价格(元)", ge=0)
    business_hours: Optional[str] = Field(None, description="营业时间，如 '08:00-17:00' 或 '全天开放'")
    suggested_duration: int = Field(60, description="建议停留时长(分钟)", ge=5)
    tags: List[str] = Field(default_factory=list, description="标签列表")
    ugc_keywords: List[str] = Field(default_factory=list, description="UGC高频关键词")
    ugc_sentiment_score: float = Field(0.0, description="UGC整体情感分 -1~+1")
    ugc_scene_tags: List[str] = Field(default_factory=list, description="UGC场景标签，如'适合亲子'")
    ugc_recent_warn: Optional[str] = Field(None, description="近期负面预警，如'五一排队3小时'")
    highlights: Optional[str] = Field(None, description="亮点简介")
    photos: Optional[List[str]] = Field(None, description="图片URL列表")
    suitable_for: Optional[List[str]] = Field(None, description="适合人群")
    source: str = Field("mock", description="数据来源")
    
    # 用于召回排序的预计算分数（非API返回字段）
    preference_match_score: float = Field(0.0, exclude=True)
    crowd_match_score: float = Field(0.0, exclude=True)
    pre_score: float = Field(0.0, exclude=True)
    
    # 混合筛选器附加字段（非API返回字段）
    llm_match_score: float = Field(0.0, exclude=True)
    filter_source: str = Field("rule", exclude=True)  # "rule" / "llm" / "hybrid"


class UserPreference(BaseModel):
    """
    用户偏好向量
    由意图理解模块从自然语言输入中提取
    """
    theme_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="主题偏好权重，如 {'美食': 0.85, '拍照': 0.92}",
        example={"美食": 0.85, "拍照": 0.92, "文化": 0.30, "自然": 0.60, "购物": 0.20}
    )
    traveler_type: str = Field(
        "独自",
        description="出行人群：独自/情侣/亲子/朋友/家庭"
    )
    pace_preference: str = Field(
        "适中",
        description="节奏偏好：紧凑/适中/悠闲"
    )
    budget_level: Optional[str] = Field(
        None,
        description="预算级别：经济/标准/高端"
    )
    willingness_to_queue: float = Field(
        0.5,
        description="是否愿意排队 0~1",
        ge=0, le=1
    )
    willingness_to_walk: float = Field(
        0.5,
        description="是否愿意多走路 0~1",
        ge=0, le=1
    )
    price_sensitivity: float = Field(
        0.5,
        description="价格敏感度 0~1，越高越在意价格",
        ge=0, le=1
    )
    
    @property
    def poi_score_weights(self) -> Dict[str, float]:
        """
        将用户偏好转换为POI评分的多目标权重
        直接影响贪心选择时的POI得分计算
        """
        max_theme = max(self.theme_weights.values()) if self.theme_weights else 0
        pace_efficiency = {
            "紧凑": 0.55,
            "适中": 0.30,
            "悠闲": 0.15
        }.get(self.pace_preference, 0.30)
        
        return {
            "experience": 0.2 + max_theme * 0.3,
            "time_efficiency": pace_efficiency,
            "cost": 0.25 if self.price_sensitivity > 0.5 else 0.1,
            "preference_match": 0.2 + (sum(self.theme_weights.values()) / max(len(self.theme_weights), 1)) * 0.2,
        }


class RouteConstraints(BaseModel):
    """路线约束条件"""
    city: str = Field(..., description="目标城市")
    start_time: str = Field(..., description="开始时间，如 '09:00'")
    end_time: str = Field(..., description="结束时间，如 '18:00'")
    start_point: Optional[Location] = Field(
        None,
        description="起点坐标，不传则使用城市中心"
    )
    budget: Optional[int] = Field(
        None,
        description="总预算(元)",
        ge=0
    )
    must_visit: List[str] = Field(
        default_factory=list,
        description="必去POI名称列表"
    )
    avoid: List[str] = Field(
        default_factory=list,
        description="不想去的POI名称列表"
    )
    transport_mode: str = Field(
        "步行",
        description="交通方式：步行/骑行/驾车/公交"
    )


class PlanSegment(BaseModel):
    """路线中的一个POI节点"""
    poi: POI = Field(..., description="POI信息")
    arrive_time: str = Field(..., description="到达时间，如 '09:30'")
    leave_time: str = Field(..., description="离开时间，如 '11:00'")
    duration: int = Field(..., description="停留时长(分钟)")
    transport_to_next: Optional[str] = Field(
        None,
        description="到下一个POI的交通方式及耗时"
    )
    transport_distance_m: Optional[int] = Field(
        None,
        description="到下一个POI的距离(米)"
    )
    transport_mode: Optional[str] = Field(
        None,
        description="实际使用的交通方式：步行/骑行/驾车/公交"
    )
    tips: Optional[str] = Field(
        None,
        description="个性化提示，如 '上午光线适合拍照'"
    )
    selection_reasons: List[str] = Field(
        default_factory=list,
        description="该POI被选中的偏好原因"
    )


class RoutePlan(BaseModel):
    """一条完整路线方案"""
    plan_id: str = Field(..., description="方案ID")
    theme: str = Field(..., description="方案主题，如 '深度体验' / '高效省时' / '均衡推荐'")
    description: str = Field(..., description="方案一句话描述")
    total_time: str = Field(..., description="总用时，如 '6小时30分'")
    total_cost: int = Field(..., description="总花费(元)")
    poi_count: int = Field(..., description="POI数量")
    segments: List[PlanSegment] = Field(..., description="路线节点列表")
    overall_reasoning: str = Field(
        ...,
        description="整体推荐理由（偏好对齐）"
    )
    preference_weights_used: Optional[Dict[str, float]] = Field(
        None,
        description="该方案使用的偏好权重（用于解释差异）"
    )
    is_overtime: bool = Field(
        False,
        description="是否超出结束时间"
    )
    overtime_minutes: int = Field(
        0,
        description="超出结束时间的分钟数"
    )
    overtime_candidates: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="可删减的POI候选列表（按优先级排序）"
    )


class PlanRequest(BaseModel):
    """
    POST /api/plan 请求体
    用户输入 → 路线规划请求
    """
    raw_query: Optional[str] = Field(
        None,
        description="自然语言输入，如 '周末带女朋友去杭州玩，喜欢拍照和吃辣'"
    )
    city: str = Field(..., description="目标城市")
    date: Optional[str] = Field(None, description="日期，如 '2024-06-15'")
    start_time: str = Field("09:00", description="开始时间")
    end_time: str = Field("18:00", description="结束时间")
    budget: Optional[int] = Field(None, description="预算(元)")
    must_visit: List[str] = Field(default_factory=list, description="必去点")
    avoid: List[str] = Field(default_factory=list, description="不想去")
    travelers: str = Field("独自", description="出行人群")
    preferences: List[str] = Field(
        default_factory=list,
        description="偏好标签，如 ['美食', '拍照']"
    )
    transport_mode: str = Field("步行", description="交通方式")
    pace: str = Field("适中", description="节奏：紧凑/适中/悠闲")


class RankedPOI(BaseModel):
    """LLM排序后的候选POI，用于前端展示参考"""
    poi_id: str = Field(..., description="POI唯一标识")
    name: str = Field(..., description="POI名称")
    category: str = Field(..., description="一级分类")
    rating: Optional[float] = Field(None, description="评分")
    match_score: int = Field(..., description="LLM匹配分数 0-100", ge=0, le=100)
    recommendation_reason: str = Field(..., description="推荐理由")
    is_recommended: bool = Field(True, description="是否推荐")
    distance_from_start_km: Optional[float] = Field(None, description="距离起点公里数")
    location: Optional[Location] = Field(None, description="坐标")


class PlanResponse(BaseModel):
    """
    POST /api/plan 响应体
    """
    request_id: str = Field(..., description="请求ID")
    user_preference: UserPreference = Field(..., description="解析出的用户偏好")
    plans: List[RoutePlan] = Field(..., description="路线方案列表（通常3条）")
    candidate_pois_count: int = Field(..., description="召回的候选POI数量")
    ranked_candidates: Optional[List[RankedPOI]] = Field(
        None, description="LLM排序后的候选POI列表（供用户参考和手动添加）"
    )


class AdjustRequest(BaseModel):
    """
    POST /api/plan/{plan_id}/adjust 请求体
    动态调整约束
    """
    mode: str = Field("replan", description="调整模式：replan=重新规划，arrange=增量编排")
    end_time: Optional[str] = Field(None, description="调整后的结束时间")
    budget: Optional[int] = Field(None, description="调整后的预算")
    add_poi: Optional[List[str]] = Field(None, description="新增的必去POI")
    remove_poi: Optional[List[str]] = Field(None, description="要移除的POI")
    preference_shift: Optional[Dict[str, float]] = Field(
        None,
        description="偏好权重微调，如 {'美食': 0.2} 表示增加美食权重"
    )
