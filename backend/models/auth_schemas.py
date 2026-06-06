# -*- coding: utf-8 -*-
"""
认证相关数据模型 (Pydantic)
"""

from typing import Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=2, max_length=32, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    phone: Optional[str] = Field(None, description="手机号（可选）")
    profile_text: Optional[str] = Field(None, description="用户画像自然语言描述，如'我喜欢美食和拍照，不喜欢排队'")


class LoginRequest(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """登录/注册成功响应"""
    access_token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field("bearer", description="令牌类型")
    user: dict = Field(..., description="用户信息")


class UserProfileResponse(BaseModel):
    """用户画像响应"""
    user_id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    theme_weights: dict = Field(default_factory=dict, description="主题偏好权重")
    profile_description: Optional[str] = Field(None, description="用户画像自然语言描述")
    traveler_type: str = Field("独自", description="出行人群")
    pace_preference: str = Field("适中", description="节奏偏好")
    budget_level: Optional[str] = Field(None, description="预算级别")
    price_sensitivity: float = Field(0.5, description="价格敏感度")
    willingness_to_queue: float = Field(0.5, description="排队意愿")
    willingness_to_walk: float = Field(0.5, description="步行意愿")
    total_plans_generated: int = Field(0, description="总规划次数")
    total_plans_selected: int = Field(0, description="总选择次数")
    most_selected_theme: Optional[str] = Field(None, description="最常选择的主题")
    avg_budget: Optional[float] = Field(None, description="平均预算")


class FeedbackRequest(BaseModel):
    """POI 显式反馈请求"""
    poi_name: str = Field(..., description="POI 名称")
    feedback_type: str = Field(..., description="反馈类型: like / dislike")
    context: Optional[str] = Field(None, description="反馈上下文（可选）")


class SelectPlanRequest(BaseModel):
    """用户选择方案请求（隐式行为追踪）"""
    request_id: str = Field(..., description="规划请求ID")
    selected_plan_theme: str = Field(..., description="选择的方案主题")
    selected_poi_names: list = Field(default_factory=list, description="方案包含的POI名称列表")
    total_cost: Optional[int] = Field(None, description="方案总花费")
    total_time: Optional[str] = Field(None, description="方案总时间")


class UpdateProfileRequest(BaseModel):
    """更新用户画像请求"""
    profile_text: Optional[str] = Field(None, description="画像自然语言描述（可选，提供时会触发LLM解析）")
    profile_description: Optional[str] = Field(None, description="画像自然语言描述（直接保存，不触发LLM解析）")
    theme_weights: Optional[dict] = Field(None, description="主题权重字典")
    traveler_type: Optional[str] = Field(None, description="出行人群")
    pace_preference: Optional[str] = Field(None, description="节奏偏好")
    budget_level: Optional[str] = Field(None, description="预算级别")
    price_sensitivity: Optional[float] = Field(None, description="价格敏感度", ge=0, le=1)
    willingness_to_queue: Optional[float] = Field(None, description="排队意愿", ge=0, le=1)
    willingness_to_walk: Optional[float] = Field(None, description="步行意愿", ge=0, le=1)


class PlanFeedbackRequest(BaseModel):
    """对整个方案的评分"""
    request_id: str = Field(..., description="规划请求ID")
    score: int = Field(..., ge=1, le=5, description="评分 1-5")
