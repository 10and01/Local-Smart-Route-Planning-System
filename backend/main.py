# -*- coding: utf-8 -*-
"""
FastAPI 入口
提供路线规划API服务
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware

from backend.models.schemas import PlanRequest, PlanResponse, AdjustRequest
from backend.models.auth_schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    FeedbackRequest, SelectPlanRequest, PlanFeedbackRequest,
    UserProfileResponse, UpdateProfileRequest
)
from backend.services.planner import planner_service
from backend.services.auth import (
    get_current_user, require_user, require_registered,
    hash_password, verify_password, create_access_token
)
from backend.db.database import init_db
from backend.db.models import UserDAO, UserProfileDAO, UserHistoryDAO, UserFeedbackDAO, ProfileVersionDAO
from backend.data.city_builder import (
    get_available_cities, get_city_status, start_city_build
)
from backend.data.loader import get_city_center


app = FastAPI(
    title="本地智能路线规划系统",
    description="美团AI Hackthon - 偏好驱动的本地路线规划API",
    version="2.0.0"
)

# CORS配置（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动时初始化数据库
@app.on_event("startup")
async def startup_event():
    init_db()



@app.get("/")
def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "本地智能路线规划系统",
        "version": "1.0.0"
    }


# ============================================================================
# 认证路由
# ============================================================================

@app.post("/api/auth/register", response_model=TokenResponse)
def register(req: RegisterRequest):
    """用户注册"""
    # 检查用户名是否已存在
    existing = UserDAO.get_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 检查手机号
    if req.phone:
        existing_phone = UserDAO.get_by_phone(req.phone)
        if existing_phone:
            raise HTTPException(status_code=400, detail="手机号已注册")
    
    password_hash = hash_password(req.password)
    user_id = UserDAO.create(req.username, password_hash, req.phone)
    
    # 【P2-1】若提供了 profile_text，用 LLM 初始化画像
    if req.profile_text and req.profile_text.strip():
        try:
            init_pref = planner_service.personalization.init_profile_from_text(req.profile_text.strip())
            if init_pref:
                planner_service.personalization.save_profile_to_db(
                    user_id=user_id,
                    user_type="registered",
                    preference=init_pref,
                    source="llm_init",
                    delta={"profile_text": req.profile_text.strip()}
                )
                print(f"[Register] 用户 {req.username} 通过 profile_text 初始化画像")
        except Exception as e:
            print(f"[Register] profile_text 初始化失败（非关键）: {e}")
    
    token = create_access_token(user_id, "registered")
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_id, "username": req.username}
    }


@app.post("/api/auth/login", response_model=TokenResponse)
def login(req: LoginRequest):
    """用户登录"""
    user = UserDAO.get_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    token = create_access_token(user["id"], "registered")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "username": user["username"]}
    }


@app.get("/api/auth/me")
def get_me(user: dict = Depends(require_user)):
    """获取当前用户信息"""
    return {
        "user_id": user["user_id"],
        "user_type": user["user_type"],
        "username": user.get("username"),
        "device_id": user.get("device_id"),
    }


# ============================================================================
# 用户个性化路由
# ============================================================================

@app.get("/api/user/profile")
def get_user_profile(user: dict = Depends(require_user)):
    """获取用户长期画像"""
    profile = UserProfileDAO.get(user["user_id"], user["user_type"])
    if not profile:
        raise HTTPException(status_code=404, detail="画像不存在")
    
    import json
    theme_weights = {}
    try:
        theme_weights = json.loads(profile.get("theme_weights_json", "{}"))
    except:
        pass
    
    return {
        "user_id": user["user_id"],
        "username": user.get("username"),
        "theme_weights": theme_weights,
        "traveler_type": profile.get("traveler_type", "独自"),
        "pace_preference": profile.get("pace_preference", "适中"),
        "budget_level": profile.get("budget_level"),
        "price_sensitivity": profile.get("price_sensitivity", 0.5),
        "willingness_to_queue": profile.get("willingness_to_queue", 0.5),
        "willingness_to_walk": profile.get("willingness_to_walk", 0.5),
        "total_plans_generated": profile.get("total_plans_generated", 0),
        "total_plans_selected": profile.get("total_plans_selected", 0),
        "most_selected_theme": profile.get("most_selected_theme"),
        "avg_budget": profile.get("avg_budget"),
    }


@app.put("/api/user/profile")
def update_user_profile(req: UpdateProfileRequest, user: dict = Depends(require_user)):
    """
    【P2-1】更新用户画像
    - 若提供 profile_text，触发 LLM 解析并融合到现有画像
    - 若提供具体字段，直接覆盖
    """
    profile = UserProfileDAO.get(user["user_id"], user["user_type"])
    if not profile:
        raise HTTPException(status_code=404, detail="画像不存在")

    current_pref = planner_service.personalization.profile_to_preference(profile)
    if not current_pref:
        raise HTTPException(status_code=500, detail="画像解析失败")

    delta = {}

    # 方式1: profile_text LLM 解析
    if req.profile_text and req.profile_text.strip():
        parsed = planner_service.personalization.init_profile_from_text(req.profile_text.strip())
        if parsed:
            # 平滑融合
            fused = planner_service.personalization.fuse_preferences(parsed, current_pref)
            current_pref = fused
            delta["profile_text_parsed"] = True

    # 方式2: 直接字段覆盖
    scalar_fields = [
        "traveler_type", "pace_preference", "budget_level",
        "price_sensitivity", "willingness_to_queue", "willingness_to_walk"
    ]
    for field in scalar_fields:
        val = getattr(req, field)
        if val is not None:
            setattr(current_pref, field, val)
            delta[field] = val

    if req.theme_weights is not None:
        current_pref.theme_weights = req.theme_weights
        delta["theme_weights"] = req.theme_weights

    # 值域校验
    for field in ["price_sensitivity", "willingness_to_queue", "willingness_to_walk"]:
        v = getattr(current_pref, field)
        if v is not None:
            setattr(current_pref, field, max(0.0, min(1.0, float(v))))

    if current_pref.pace_preference not in ("紧凑", "适中", "悠闲"):
        current_pref.pace_preference = "适中"
    if current_pref.budget_level not in ("经济", "标准", "高端"):
        current_pref.budget_level = "标准"

    planner_service.personalization.save_profile_to_db(
        user_id=user["user_id"],
        user_type=user["user_type"],
        preference=current_pref,
        source="user_manual",
        delta=delta
    )

    return {"status": "ok", "message": "画像已更新"}


@app.get("/api/user/profile/history")
def get_profile_history(
    limit: int = 20,
    user: dict = Depends(require_user)
):
    """
    【P2-1】获取用户画像版本历史
    """
    versions = ProfileVersionDAO.get_by_user(user["user_id"], user["user_type"], limit)
    import json
    for v in versions:
        try:
            v["delta_json"] = json.loads(v.get("delta_json", "{}"))
        except:
            v["delta_json"] = {}
        try:
            v["profile_snapshot_json"] = json.loads(v.get("profile_snapshot_json", "{}"))
        except:
            v["profile_snapshot_json"] = {}
    return {"versions": versions}


@app.get("/api/user/history")
def get_user_history(
    limit: int = 20,
    user: dict = Depends(require_user)
):
    """获取用户历史规划记录"""
    history = UserHistoryDAO.get_by_user(user["user_id"], user["user_type"], limit)
    return {"history": history}


@app.get("/api/user/history/{request_id}")
def get_history_detail(request_id: str, user: dict = Depends(require_user)):
    """获取某次规划的详情"""
    entry = UserHistoryDAO.get_by_request_id(request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="记录不存在")
    if entry["user_id"] != user["user_id"] or entry["user_type"] != user["user_type"]:
        raise HTTPException(status_code=403, detail="无权访问")
    return entry


@app.post("/api/user/feedback")
def create_feedback(
    req: FeedbackRequest,
    user: dict = Depends(require_user)
):
    """提交 POI 显式反馈"""
    if req.feedback_type not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="feedback_type 必须是 like 或 dislike")
    
    UserFeedbackDAO.create_or_update(
        user_id=user["user_id"],
        user_type=user["user_type"],
        poi_name=req.poi_name,
        feedback_type=req.feedback_type,
        context=req.context
    )
    return {"status": "ok", "message": "反馈已记录"}


@app.post("/api/user/select-plan")
def select_plan(req: SelectPlanRequest, user: dict = Depends(require_user)):
    """记录用户选择了哪个方案（隐式行为追踪）"""
    UserHistoryDAO.select_plan(
        request_id=req.request_id,
        selected_plan_theme=req.selected_plan_theme,
        selected_poi_names=req.selected_poi_names,
        total_cost=req.total_cost,
        total_time=req.total_time
    )
    
    # 同时触发画像演化
    planner_service.personalization.evolve_profile(
        user_id=user["user_id"],
        user_type=user["user_type"],
        selected_plan_theme=req.selected_plan_theme,
        selected_poi_names=req.selected_poi_names
    )
    
    return {"status": "ok", "message": "选择已记录"}


@app.post("/api/user/plan-feedback")
def plan_feedback(req: PlanFeedbackRequest, user: dict = Depends(require_user)):
    """对整个方案评分"""
    UserHistoryDAO.update_feedback_score(req.request_id, req.score)
    return {"status": "ok", "message": "评分已记录"}


# ============================================================================
# 规划路由（改造：支持用户注入）
# ============================================================================

@app.post("/api/plan", response_model=PlanResponse)
def create_plan(
    request: PlanRequest,
    user: dict = Depends(get_current_user)
):
    """
    创建路线规划（支持用户画像融合）
    """
    try:
        user_id = user["user_id"] if user else None
        user_type = user["user_type"] if user else None
        response = planner_service.plan(request, user_id=user_id, user_type=user_type)
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"规划失败: {str(e)}")


@app.post("/api/plan/{request_id}/adjust", response_model=PlanResponse)
def adjust_plan(request_id: str, adjust: AdjustRequest):
    """
    动态调整已有方案（从持久化缓存读取）
    【P1】支持 mode="replan" 重新规划 或 mode="arrange" 增量编排
    """
    try:
        response = planner_service.adjust_plan(
            request_id=request_id,
            mode=adjust.mode,
            end_time=adjust.end_time,
            budget=adjust.budget,
            add_poi=adjust.add_poi,
            remove_poi=adjust.remove_poi,
            preference_shift=adjust.preference_shift
        )
        if response is None:
            raise HTTPException(status_code=404, detail="方案不存在")
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调整失败: {str(e)}")


@app.get("/api/plan/{request_id}/candidates")
def get_plan_candidates(request_id: str):
    """
    【P1】获取某次规划的备选池（Top-40 候选 POI）
    返回每个 POI 的规则分数、LLM精排分数、推荐理由、是否已在方案中
    """
    try:
        result = planner_service.get_candidates(request_id)
        if result is None:
            raise HTTPException(status_code=404, detail="方案不存在或已过期")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取备选池失败: {str(e)}")


@app.get("/api/plan/{request_id}")
def get_plan(request_id: str):
    """获取已生成的方案详情（支持持久化缓存）"""
    # 优先查内存热点缓存
    cached = planner_service._hot_cache.get(request_id)
    if cached:
        return {
            "request_id": request_id,
            "user_preference": cached["user_pref"],
            "plans": cached["plans"],
            "candidate_pois_count": len(cached["candidates"])
        }
    
    # 回退到数据库
    from backend.db.models import PlanCacheDAO
    db_cached = PlanCacheDAO.get(request_id)
    if db_cached:
        import json
        return {
            "request_id": request_id,
            "user_preference": json.loads(db_cached["request_json"]).get("user_preference", {}),
            "plans": json.loads(db_cached["response_json"]).get("plans", []),
            "candidate_pois_count": json.loads(db_cached["response_json"]).get("candidate_pois_count", 0)
        }
    
    raise HTTPException(status_code=404, detail="方案不存在")


@app.get("/api/cities")
def get_cities():
    """获取支持的城市列表（动态扫描已有数据）"""
    city_names = get_available_cities()
    if not city_names:
        city_names = ["杭州"]
    
    # 为每个城市补充中心坐标
    result = []
    for city in city_names:
        center = get_city_center(city)
        status = get_city_status(city)
        result.append({
            "name": city,
            "center": center,
            "status": status["status"],
            "progress": status["progress"]
        })
    
    return {
        "cities": result,
        "default_city": "杭州"
    }


@app.post("/api/cities/{city}/init")
def init_city(city: str):
    """
    初始化城市POI数据
    首次访问新城市时调用，后台异步构建数据
    """
    status = get_city_status(city)
    
    if status["status"] == "done":
        return {
            "city": city,
            "status": "done",
            "message": "该城市数据已就绪",
            "progress": 100
        }
    
    # 启动后台构建
    new_status = start_city_build(city)
    return {
        "city": city,
        "status": new_status["status"],
        "message": new_status["message"],
        "progress": new_status["progress"]
    }


@app.get("/api/cities/{city}/status")
def city_status(city: str):
    """查询城市数据构建状态"""
    status = get_city_status(city)
    center = get_city_center(city)
    return {
        "city": city,
        "center": center,
        **status
    }


@app.post("/api/_reload")
def force_reload():
    """强制重启后端服务（加载最新代码和配置）"""
    import os
    os._exit(0)
    return {"status": "reloading"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
