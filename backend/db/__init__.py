# -*- coding: utf-8 -*-
"""
数据库模块
SQLite 持久层，支持用户系统、画像、历史记录、方案缓存
"""

from backend.db.database import get_db, init_db
from backend.db.models import (
    create_tables, drop_tables,
    UserDAO, UserProfileDAO, UserHistoryDAO, UserFeedbackDAO,
    PlanCacheDAO, DirectionCacheDAO, DynamicFetchCacheDAO
)

__all__ = [
    "get_db", "init_db",
    "create_tables", "drop_tables",
    "UserDAO", "UserProfileDAO", "UserHistoryDAO", "UserFeedbackDAO",
    "PlanCacheDAO", "DirectionCacheDAO", "DynamicFetchCacheDAO",
]
