"""Database initialization and schema for Agentic Memory."""
import sqlite3
from config import DB_PATH


def init_db() -> sqlite3.Connection:
    """Initialize database with required schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    # Enable extensions
    cursor.execute("PRAGMA busy_timeout = 5000;")
    cursor.execute("PRAGMA auto_vacuum = INCREMENTAL;")
    cursor.execute("PRAGMA journal_mode = WAL;")

    # Durable Knowledge (OKF format)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS durable_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            category TEXT NOT NULL,
            file_path TEXT,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Full-text search for durable knowledge
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_durable_knowledge
        USING fts5(title, content, category, content=durable_knowledge, content_rowid=id)
    """)

    # Short-Lived Context (episodic notes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS short_lived_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            lesson TEXT,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TIMESTAMP,
            pattern_hash TEXT,
            fixed_lesson INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Full-text search for context
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_short_lived_context
        USING fts5(title, content, lesson, content=short_lived_context, content_rowid=id)
    """)

    # Task Skills (workflows and procedures)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            steps TEXT,
            tags TEXT,
            file_path TEXT,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Full-text search for skills
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_task_skills
        USING fts5(name, steps, tags, content=task_skills, content_rowid=id)
    """)

    # Search cache for RRF results
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            query_hash TEXT PRIMARY KEY,
            results TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ttl_seconds INTEGER DEFAULT 3600
        )
    """)

    # Migrate databases created by older versions.
    cursor.execute("PRAGMA table_info(short_lived_context)")
    columns = {row[1] for row in cursor.fetchall()}
    for name, definition in (
        ("access_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_accessed_at", "TIMESTAMP"),
        ("pattern_hash", "TEXT"),
        ("fixed_lesson", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            cursor.execute(f"ALTER TABLE short_lived_context ADD COLUMN {name} {definition}")

    db.commit()
    return db


def get_db() -> sqlite3.Connection:
    """Get or create database connection."""
    if not DB_PATH.exists():
        return init_db()
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db
