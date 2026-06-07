# -*- coding: utf-8 -*-
"""
数据库模型定义与 DAO 层
所有 SQLite 表结构 + 数据访问对象
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from backend.db.database import get_db


# ============================================================================
# 建表 / 删表
# ============================================================================

CREATE_TABLES_SQL = """
-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    phone TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 匿名用户表(device_id 追踪)
CREATE TABLE IF NOT EXISTS anonymous_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户画像表(长期偏好累积)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme_weights_json TEXT NOT NULL DEFAULT '{}',
    profile_description TEXT,
    traveler_type TEXT DEFAULT '独自',
    pace_preference TEXT DEFAULT '适中',
    budget_level TEXT,
    price_sensitivity REAL DEFAULT 0.5,
    willingness_to_queue REAL DEFAULT 0.5,
    willingness_to_walk REAL DEFAULT 0.5,
    total_plans_generated INTEGER DEFAULT 0,
    total_plans_selected INTEGER DEFAULT 0,
    most_selected_theme TEXT,
    avg_budget REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 匿名用户画像表
CREATE TABLE IF NOT EXISTS anonymous_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES anonymous_users(id) ON DELETE CASCADE,
    theme_weights_json TEXT NOT NULL DEFAULT '{}',
    profile_description TEXT,
    traveler_type TEXT DEFAULT '独自',
    pace_preference TEXT DEFAULT '适中',
    budget_level TEXT,
    price_sensitivity REAL DEFAULT 0.5,
    willingness_to_queue REAL DEFAULT 0.5,
    willingness_to_walk REAL DEFAULT 0.5,
    total_plans_generated INTEGER DEFAULT 0,
    total_plans_selected INTEGER DEFAULT 0,
    most_selected_theme TEXT,
    avg_budget REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 历史记录表
CREATE TABLE IF NOT EXISTS user_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_type TEXT NOT NULL DEFAULT 'registered' CHECK(user_type IN ('registered', 'anonymous')),
    request_id TEXT NOT NULL UNIQUE,
    city TEXT NOT NULL,
    raw_query TEXT,
    selected_plan_theme TEXT,
    selected_poi_names_json TEXT,
    total_cost INTEGER,
    total_time TEXT,
    feedback_score INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 画像版本历史表（每次LLM增量更新或用户手动更新时记录）
CREATE TABLE IF NOT EXISTS profile_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_type TEXT NOT NULL DEFAULT 'registered' CHECK(user_type IN ('registered', 'anonymous')),
    source TEXT NOT NULL CHECK(source IN ('llm_init', 'llm_delta', 'user_manual', 'behavior_ema')),
    delta_json TEXT NOT NULL DEFAULT '{}',
    profile_snapshot_json TEXT NOT NULL DEFAULT '{}',
    request_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_profile_versions_user ON profile_versions(user_id, user_type, created_at);

-- 用户反馈表(POI 级别)
CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_type TEXT NOT NULL DEFAULT 'registered' CHECK(user_type IN ('registered', 'anonymous')),
    poi_name TEXT NOT NULL,
    feedback_type TEXT NOT NULL CHECK(feedback_type IN ('like', 'dislike')),
    context TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, user_type, poi_name) ON CONFLICT REPLACE
);

-- 方案缓存表
CREATE TABLE IF NOT EXISTS plan_cache (
    request_id TEXT PRIMARY KEY,
    user_id INTEGER,
    user_type TEXT DEFAULT 'registered' CHECK(user_type IN ('registered', 'anonymous')),
    city TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    filter_metadata_json TEXT,
    candidate_pool_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 距离查询缓存表
CREATE TABLE IF NOT EXISTS direction_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_lat REAL NOT NULL,
    from_lng REAL NOT NULL,
    to_lat REAL NOT NULL,
    to_lng REAL NOT NULL,
    mode TEXT NOT NULL,
    distance_m INTEGER,
    duration_sec INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_lat, from_lng, to_lat, to_lng, mode) ON CONFLICT REPLACE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id, user_type, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON user_feedback(user_id, user_type);
CREATE INDEX IF NOT EXISTS idx_plan_cache_user ON plan_cache(user_id, user_type, created_at);
CREATE INDEX IF NOT EXISTS idx_direction_cache ON direction_cache(from_lat, from_lng, to_lat, to_lng, mode);

-- 动态抓取结果缓存表
CREATE TABLE IF NOT EXISTS dynamic_fetch_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(city, query_hash)
);

CREATE INDEX IF NOT EXISTS idx_dynamic_fetch_lookup 
ON dynamic_fetch_cache(city, query_hash);
"""


def create_tables():
    """创建所有表"""
    with get_db() as conn:
        conn.executescript(CREATE_TABLES_SQL)


def run_migrations():
    """运行数据库迁移（向后兼容增加字段）"""
    with get_db() as conn:
        # 用户画像描述字段
        for table in ("user_profiles", "anonymous_profiles"):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN profile_description TEXT")
            except sqlite3.OperationalError:
                pass  # 字段已存在
        # 方案缓存候选池字段
        try:
            conn.execute("ALTER TABLE plan_cache ADD COLUMN candidate_pool_json TEXT")
        except sqlite3.OperationalError:
            pass


def drop_tables():
    """删除所有表(测试用)"""
    with get_db() as conn:
        conn.executescript("""
            DROP TABLE IF EXISTS user_feedback;
            DROP TABLE IF EXISTS user_history;
            DROP TABLE IF EXISTS anonymous_profiles;
            DROP TABLE IF EXISTS user_profiles;
            DROP TABLE IF EXISTS plan_cache;
            DROP TABLE IF EXISTS direction_cache;
            DROP TABLE IF EXISTS profile_versions;
            DROP TABLE IF EXISTS anonymous_users;
            DROP TABLE IF EXISTS users;
        """)


# ============================================================================
# DAO 基类
# ============================================================================

class BaseDAO:
    """DAO 基类，提供通用的 CRUD 辅助方法"""
    
    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}


# ============================================================================
# 用户 DAO
# ============================================================================

class UserDAO(BaseDAO):
    """注册用户 DAO"""
    
    @staticmethod
    def create(username: str, password_hash: str, phone: Optional[str] = None) -> int:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, phone) VALUES (?, ?, ?)",
                (username, password_hash, phone)
            )
            user_id = cursor.lastrowid
            # 同时创建空画像
            conn.execute(
                "INSERT INTO user_profiles (user_id) VALUES (?)",
                (user_id,)
            )
            return user_id
    
    @staticmethod
    def get_by_username(username: str) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            return UserDAO._row_to_dict(row)
    
    @staticmethod
    def get_by_id(user_id: int) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return UserDAO._row_to_dict(row)
    
    @staticmethod
    def get_by_phone(phone: str) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE phone = ?", (phone,)
            ).fetchone()
            return UserDAO._row_to_dict(row)


class AnonymousUserDAO(BaseDAO):
    """匿名用户 DAO"""
    
    @staticmethod
    def get_or_create(device_id: str) -> int:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id FROM anonymous_users WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row:
                return row["id"]
            cursor = conn.execute(
                "INSERT INTO anonymous_users (device_id) VALUES (?)",
                (device_id,)
            )
            user_id = cursor.lastrowid
            # 同时创建空画像
            conn.execute(
                "INSERT INTO anonymous_profiles (user_id) VALUES (?)",
                (user_id,)
            )
            return user_id
    
    @staticmethod
    def get_by_device_id(device_id: str) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM anonymous_users WHERE device_id = ?", (device_id,)
            ).fetchone()
            return AnonymousUserDAO._row_to_dict(row)


# ============================================================================
# 用户画像 DAO
# ============================================================================

class UserProfileDAO(BaseDAO):
    """用户画像 DAO(同时支持 registered 和 anonymous)"""
    
    @staticmethod
    def _table_name(user_type: str) -> str:
        return "user_profiles" if user_type == "registered" else "anonymous_profiles"
    
    @staticmethod
    def get(user_id: int, user_type: str = "registered") -> Optional[Dict[str, Any]]:
        table = UserProfileDAO._table_name(user_type)
        with get_db() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)
            ).fetchone()
            return UserProfileDAO._row_to_dict(row)
    
    @staticmethod
    def update_theme_weights(user_id: int, user_type: str, weights: Dict[str, float]):
        table = UserProfileDAO._table_name(user_type)
        with get_db() as conn:
            conn.execute(
                f"UPDATE {table} SET theme_weights_json = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (json.dumps(weights, ensure_ascii=False), user_id)
            )
    
    @staticmethod
    def update_stats(user_id: int, user_type: str, **kwargs):
        """更新统计字段，如 total_plans_generated, most_selected_theme 等"""
        table = UserProfileDAO._table_name(user_type)
        allowed = {"total_plans_generated", "total_plans_selected", "most_selected_theme",
                   "avg_budget", "traveler_type", "pace_preference", "budget_level",
                   "price_sensitivity", "willingness_to_queue", "willingness_to_walk",
                   "profile_description", "theme_weights_json"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [user_id]
        
        with get_db() as conn:
            conn.execute(
                f"UPDATE {table} SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                values
            )


# ============================================================================
# 画像版本历史 DAO
# ============================================================================

class ProfileVersionDAO(BaseDAO):
    """画像版本历史 DAO：记录每次画像变更的来源和增量"""

    @staticmethod
    def create(
        user_id: int,
        user_type: str,
        source: str,  # 'llm_init', 'llm_delta', 'user_manual', 'behavior_ema'
        delta: Dict[str, Any],
        profile_snapshot: Dict[str, Any],
        request_id: Optional[str] = None
    ) -> int:
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO profile_versions
                   (user_id, user_type, source, delta_json, profile_snapshot_json, request_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, user_type, source,
                 json.dumps(delta, ensure_ascii=False),
                 json.dumps(profile_snapshot, ensure_ascii=False),
                 request_id)
            )
            return cursor.lastrowid

    @staticmethod
    def get_by_user(user_id: int, user_type: str = "registered", limit: int = 50) -> List[Dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM profile_versions
                   WHERE user_id = ? AND user_type = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, user_type, limit)
            ).fetchall()
            return [ProfileVersionDAO._row_to_dict(r) for r in rows]

    @staticmethod
    def get_latest(user_id: int, user_type: str = "registered") -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                """SELECT * FROM profile_versions
                   WHERE user_id = ? AND user_type = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id, user_type)
            ).fetchone()
            return ProfileVersionDAO._row_to_dict(row)


# ============================================================================
# 历史记录 DAO
# ============================================================================

class UserHistoryDAO(BaseDAO):
    """用户历史规划记录 DAO"""
    
    @staticmethod
    def create(
        user_id: int,
        user_type: str,
        request_id: str,
        city: str,
        raw_query: Optional[str] = None,
        selected_plan_theme: Optional[str] = None,
        selected_poi_names: Optional[List[str]] = None,
        total_cost: Optional[int] = None,
        total_time: Optional[str] = None,
        feedback_score: Optional[int] = None
    ) -> int:
        with get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO user_history 
                   (user_id, user_type, request_id, city, raw_query, 
                    selected_plan_theme, selected_poi_names_json, total_cost, total_time, feedback_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, user_type, request_id, city, raw_query,
                 selected_plan_theme,
                 json.dumps(selected_poi_names, ensure_ascii=False) if selected_poi_names else None,
                 total_cost, total_time, feedback_score)
            )
            return cursor.lastrowid
    
    @staticmethod
    def select_plan(request_id: str, selected_plan_theme: str, selected_poi_names: List[str],
                    total_cost: Optional[int] = None, total_time: Optional[str] = None):
        """用户前端选择了某套方案"""
        with get_db() as conn:
            conn.execute(
                """UPDATE user_history 
                   SET selected_plan_theme = ?, selected_poi_names_json = ?, total_cost = ?, total_time = ?
                   WHERE request_id = ?""",
                (selected_plan_theme,
                 json.dumps(selected_poi_names, ensure_ascii=False),
                 total_cost, total_time, request_id)
            )
    
    @staticmethod
    def get_by_user(user_id: int, user_type: str = "registered", limit: int = 50) -> List[Dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM user_history 
                   WHERE user_id = ? AND user_type = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, user_type, limit)
            ).fetchall()
            return [UserHistoryDAO._row_to_dict(r) for r in rows]
    
    @staticmethod
    def get_by_request_id(request_id: str) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM user_history WHERE request_id = ?", (request_id,)
            ).fetchone()
            return UserHistoryDAO._row_to_dict(row)
    
    @staticmethod
    def update_feedback_score(request_id: str, score: int):
        with get_db() as conn:
            conn.execute(
                "UPDATE user_history SET feedback_score = ? WHERE request_id = ?",
                (score, request_id)
            )


# ============================================================================
# 用户反馈 DAO
# ============================================================================

class UserFeedbackDAO(BaseDAO):
    """POI 级别显式反馈 DAO"""
    
    @staticmethod
    def create_or_update(
        user_id: int,
        user_type: str,
        poi_name: str,
        feedback_type: str,  # 'like' or 'dislike'
        context: Optional[str] = None
    ):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO user_feedback (user_id, user_type, poi_name, feedback_type, context)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, user_type, poi_name) DO UPDATE SET
                   feedback_type = excluded.feedback_type,
                   context = excluded.context,
                   created_at = CURRENT_TIMESTAMP""",
                (user_id, user_type, poi_name, feedback_type, context)
            )
    
    @staticmethod
    def get_by_user(user_id: int, user_type: str = "registered") -> List[Dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM user_feedback WHERE user_id = ? AND user_type = ?",
                (user_id, user_type)
            ).fetchall()
            return [UserFeedbackDAO._row_to_dict(r) for r in rows]


# ============================================================================
# 方案缓存 DAO
# ============================================================================

class PlanCacheDAO(BaseDAO):
    """路线方案持久化缓存 DAO"""
    
    @staticmethod
    def create(
        request_id: str,
        user_id: Optional[int],
        user_type: Optional[str],
        city: str,
        request_json: str,
        response_json: str,
        filter_metadata_json: Optional[str] = None,
        candidate_pool_json: Optional[str] = None
    ):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO plan_cache 
                   (request_id, user_id, user_type, city, request_json, response_json, filter_metadata_json, candidate_pool_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(request_id) DO UPDATE SET
                   response_json = excluded.response_json,
                   filter_metadata_json = excluded.filter_metadata_json,
                   candidate_pool_json = excluded.candidate_pool_json,
                   created_at = CURRENT_TIMESTAMP""",
                (request_id, user_id, user_type, city, request_json, response_json, filter_metadata_json, candidate_pool_json)
            )
    
    @staticmethod
    def get(request_id: str) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM plan_cache WHERE request_id = ?", (request_id,)
            ).fetchone()
            return PlanCacheDAO._row_to_dict(row)
    
    @staticmethod
    def delete_old(days: int = 30):
        """清理过期缓存"""
        with get_db() as conn:
            conn.execute(
                "DELETE FROM plan_cache WHERE created_at < datetime('now', '-{} days')".format(days)
            )


# ============================================================================
# 距离查询缓存 DAO
# ============================================================================

class DirectionCacheDAO(BaseDAO):
    """高德路径规划结果缓存 DAO"""
    
    @staticmethod
    def get(from_lat: float, from_lng: float, to_lat: float, to_lng: float, mode: str) -> Optional[Dict[str, Any]]:
        with get_db() as conn:
            row = conn.execute(
                """SELECT * FROM direction_cache 
                   WHERE from_lat = ? AND from_lng = ? AND to_lat = ? AND to_lng = ? AND mode = ?""",
                (round(from_lat, 6), round(from_lng, 6), round(to_lat, 6), round(to_lng, 6), mode)
            ).fetchone()
            if row:
                data = DirectionCacheDAO._row_to_dict(row)
                # 检查缓存是否过期(30天)
                created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
                if datetime.now(created.tzinfo) - created > timedelta(days=30):
                    return None
                return data
            return None
    
    @staticmethod
    def save(from_lat: float, from_lng: float, to_lat: float, to_lng: float,
             mode: str, distance_m: int, duration_sec: int):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO direction_cache (from_lat, from_lng, to_lat, to_lng, mode, distance_m, duration_sec)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(from_lat, from_lng, to_lat, to_lng, mode) DO UPDATE SET
                   distance_m = excluded.distance_m,
                   duration_sec = excluded.duration_sec,
                   created_at = CURRENT_TIMESTAMP""",
                (round(from_lat, 6), round(from_lng, 6), round(to_lat, 6), round(to_lng, 6),
                 mode, distance_m, duration_sec)
            )
    
    @staticmethod
    def delete_old(days: int = 7):
        with get_db() as conn:
            conn.execute(
                "DELETE FROM direction_cache WHERE created_at < datetime('now', '-{} days')".format(days)
            )


# ============================================================================
# 动态抓取缓存 DAO
# ============================================================================

class DynamicFetchCacheDAO(BaseDAO):
    """动态POI抓取结果缓存 DAO"""
    
    @staticmethod
    def get(city: str, query_hash: str) -> Optional[str]:
        with get_db() as conn:
            row = conn.execute(
                """SELECT results_json FROM dynamic_fetch_cache
                   WHERE city = ? AND query_hash = ?
                   AND created_at > datetime('now', '-1 day')""",
                (city, query_hash)
            ).fetchone()
            return row["results_json"] if row else None
    
    @staticmethod
    def save(city: str, query_hash: str, results_json: str):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO dynamic_fetch_cache (city, query_hash, results_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(city, query_hash) DO UPDATE SET
                   results_json = excluded.results_json,
                   created_at = CURRENT_TIMESTAMP""",
                (city, query_hash, results_json)
            )
    
    @staticmethod
    def delete_old(days: int = 1):
        """清理过期缓存"""
        with get_db() as conn:
            conn.execute(
                "DELETE FROM dynamic_fetch_cache WHERE created_at < datetime('now', '-{} days')".format(days)
            )
