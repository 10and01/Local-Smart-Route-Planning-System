# -*- coding: utf-8 -*-
"""
SQLite 数据库连接管理
提供线程安全的连接池和上下文管理器
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "app.db")

# 线程本地存储
_local = threading.local()


def _get_thread_conn() -> sqlite3.Connection:
    """获取当前线程的数据库连接"""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA foreign_keys = ON")
    return _local.conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    数据库连接上下文管理器
    使用方式:
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM users")
            ...
    """
    conn = _get_thread_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """初始化数据库：创建所有表并运行迁移"""
    from backend.db.models import create_tables, run_migrations
    create_tables()
    run_migrations()
    print(f"[DB] 数据库已初始化: {DB_PATH}")


def close_db():
    """关闭当前线程的数据库连接"""
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None
