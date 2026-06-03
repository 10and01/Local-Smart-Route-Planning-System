# -*- coding: utf-8 -*-
"""
认证服务
JWT 签发/验证 + bcrypt 密码哈希
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
import bcrypt
from fastapi import HTTPException, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.db.models import UserDAO, AnonymousUserDAO

# JWT 配置
JWT_SECRET = os.environ.get("JWT_SECRET", "local-route-planning-secret-key-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """bcrypt 密码哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """bcrypt 密码校验"""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int, user_type: str = "registered") -> str:
    """签发 JWT"""
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": user_type,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """解析 JWT，失败返回 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
) -> Optional[Dict[str, Any]]:
    """
    FastAPI 依赖注入：解析当前用户
    
    优先级：
    1. JWT Bearer Token → 登录用户
    2. X-Device-Id Header → 匿名用户（自动创建）
    3. 两者都没有 → None（完全匿名，不追踪）
    
    返回格式：
    {
        "user_id": int,
        "user_type": "registered" | "anonymous",
        "username": str | None,
        "device_id": str | None,
    }
    """
    # 1. 尝试 JWT
    if credentials and credentials.credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            user_id = int(payload.get("sub", 0))
            user_type = payload.get("type", "registered")
            
            if user_type == "registered":
                user = UserDAO.get_by_id(user_id)
                if user:
                    return {
                        "user_id": user_id,
                        "user_type": "registered",
                        "username": user["username"],
                        "device_id": None,
                    }
            else:
                anon = AnonymousUserDAO.get_by_device_id(payload.get("device_id", ""))
                if anon:
                    return {
                        "user_id": user_id,
                        "user_type": "anonymous",
                        "username": None,
                        "device_id": payload.get("device_id"),
                    }
    
    # 2. 尝试 Device ID
    if x_device_id:
        anon_id = AnonymousUserDAO.get_or_create(x_device_id)
        return {
            "user_id": anon_id,
            "user_type": "anonymous",
            "username": None,
            "device_id": x_device_id,
        }
    
    # 3. 完全匿名
    return None


def require_user(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """要求必须已登录（registered 或 anonymous）"""
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录或提供设备ID")
    return user


def require_registered(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Dict[str, Any]:
    """要求必须已注册登录"""
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if user.get("user_type") != "registered":
        raise HTTPException(status_code=403, detail="该功能需要注册登录")
    return user
