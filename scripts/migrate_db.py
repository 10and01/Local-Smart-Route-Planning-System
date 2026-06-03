#!/usr/bin/env python3
"""数据库迁移脚本：新增动态抓取缓存表"""

import sqlite3
import sys
sys.path.insert(0, 'backend')

from backend.db.database import get_db

MIGRATION_SQL = """
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

def migrate():
    with get_db() as conn:
        conn.executescript(MIGRATION_SQL)
        print("[Migrate] dynamic_fetch_cache 表创建成功")
        
        # 验证表是否存在
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dynamic_fetch_cache'"
        )
        if cursor.fetchone():
            print("[Migrate] 验证通过：dynamic_fetch_cache 表已存在")
        else:
            print("[Migrate] 验证失败：表未创建")

if __name__ == "__main__":
    migrate()
