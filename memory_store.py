"""Memory storage and retrieval operations."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import json
import hashlib
import math

from embeddings import get_embedding
from config import DB_PATH
from config import (
    DECAY_LAMBDA,
    DURABLE_TIER_WEIGHT,
    PROMOTION_ACCESS_THRESHOLD,
    PROMOTION_SIMILARITY_THRESHOLD,
    RETENTION_DAYS,
    KNOWLEDGE_DIR,
    SKILLS_DIR,
)

# Ensure directories exist
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
SKILLS_DIR.mkdir(parents=True, exist_ok=True)


class MemoryStore:
    """Manages all memory tier operations."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    # ============ DURABLE KNOWLEDGE ============

    def store_okf(self, title: str, content: str, category: str) -> int:
        """Store Durable Knowledge (OKF format) as markdown file."""
        embedding = get_embedding(content)
        embedding_bytes = embedding.tobytes()

        # Save markdown file
        filename = f"{category}_{title.replace(' ', '_').lower()}.md"
        filepath = KNOWLEDGE_DIR / filename
        filepath.write_text(content, encoding="utf-8")

        # Store index in DB
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO durable_knowledge (title, content, category, embedding, file_path)
            VALUES (?, ?, ?, ?, ?)
        """, (title, content[:500], category, embedding_bytes, str(filepath)))

        # Update FTS index
        row_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO fts_durable_knowledge (rowid, title, content, category)
            VALUES (?, ?, ?, ?)
        """, (row_id, title, content[:500], category))

        self.db.commit()
        return row_id

    def get_durable_knowledge(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a durable knowledge document."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, title, content, category, file_path, created_at, updated_at
            FROM durable_knowledge WHERE id = ?
        """, (doc_id,))

        row = cursor.fetchone()
        if row:
            data = dict(row)
            # Load full content from file if available
            if data.get("file_path"):
                try:
                    file_path = Path(data["file_path"])
                    if file_path.exists():
                        data["full_content"] = file_path.read_text(encoding="utf-8")
                        data["file_path"] = str(file_path)
                except Exception:
                    pass
            return data
        return None

    def list_durable_knowledge(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all durable knowledge, optionally filtered by category."""
        cursor = self.db.cursor()

        if category:
            cursor.execute("""
                SELECT id, title, category, file_path, created_at
                FROM durable_knowledge WHERE category = ?
                ORDER BY updated_at DESC
            """, (category,))
        else:
            cursor.execute("""
                SELECT id, title, category, file_path, created_at
                FROM durable_knowledge
                ORDER BY updated_at DESC
            """)

        return [dict(row) for row in cursor.fetchall()]

    # ============ SHORT-LIVED CONTEXT ============

    def store_context(
        self,
        title: str,
        content: str,
        lesson: Optional[str] = None,
        ttl_days: int = 30,
    ) -> int:
        """Store Short-Lived Context (episodic notes) directly in DB."""
        embedding = get_embedding(content)
        embedding_bytes = embedding.tobytes()
        expires_at = datetime.now() + timedelta(days=ttl_days)

        cursor = self.db.cursor()
        pattern_hash = hashlib.sha256(" ".join(content.lower().split()).encode()).hexdigest()
        cursor.execute("""
            INSERT INTO short_lived_context
                (title, content, lesson, embedding, expires_at, pattern_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, content, lesson, embedding_bytes, expires_at, pattern_hash))

        # Update FTS index
        row_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO fts_short_lived_context (rowid, title, content, lesson)
            VALUES (?, ?, ?, ?)
        """, (row_id, title, content, lesson or ""))

        self.db.commit()
        return row_id

    def get_context(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a context note."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, title, content, lesson, created_at, expires_at,
                   access_count, last_accessed_at, pattern_hash, fixed_lesson
            FROM short_lived_context WHERE id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))
        """, (doc_id,))

        row = cursor.fetchone()
        if row:
            cursor.execute("""
                UPDATE short_lived_context
                SET access_count = access_count + 1, last_accessed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (doc_id,))
            self.db.commit()
            if row["access_count"] + 1 >= PROMOTION_ACCESS_THRESHOLD or row["fixed_lesson"]:
                self.promote_eligible_context()
            return dict(row)
        return None

    def mark_fixed_lesson(self, doc_id: int) -> None:
        """Mark a context note for immediate promotion on the next maintenance pass."""
        self.db.execute(
            "UPDATE short_lived_context SET fixed_lesson = 1 WHERE id = ?", (doc_id,)
        )
        self.db.commit()

    def list_context(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent non-expired context notes."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, title, lesson, created_at
            FROM short_lived_context
            WHERE expires_at IS NULL OR expires_at > datetime('now')
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        return [dict(row) for row in cursor.fetchall()]

    # ============ TASK SKILLS ============

    def store_skill(self, name: str, steps: str, tags: Optional[str] = None) -> int:
        """Store Task Skill (workflow/procedure) as markdown file."""
        embedding = get_embedding(steps)
        embedding_bytes = embedding.tobytes()

        # Save markdown file
        filename = f"{name.replace(' ', '_').lower()}.md"
        filepath = SKILLS_DIR / filename
        filepath.write_text(steps, encoding="utf-8")

        # Store or update in DB
        cursor = self.db.cursor()

        # Check if skill already exists
        cursor.execute("SELECT id FROM task_skills WHERE name = ?", (name,))
        existing = cursor.fetchone()

        if existing:
            row_id = existing[0]
            cursor.execute("""
                UPDATE task_skills SET steps = ?, tags = ?, embedding = ?, file_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (steps[:500], tags, embedding_bytes, str(filepath), row_id))
            # Update FTS index
            try:
                cursor.execute("DELETE FROM fts_task_skills WHERE rowid = ?", (row_id,))
            except Exception:
                pass
        else:
            cursor.execute("""
                INSERT INTO task_skills (name, steps, tags, embedding, file_path)
                VALUES (?, ?, ?, ?, ?)
            """, (name, steps[:500], tags, embedding_bytes, str(filepath)))
            row_id = cursor.lastrowid

        # Insert into FTS index
        try:
            cursor.execute("""
                INSERT INTO fts_task_skills (rowid, name, steps, tags)
                VALUES (?, ?, ?, ?)
            """, (row_id, name, steps[:500], tags or ""))
        except sqlite3.IntegrityError:
            pass

        self.db.commit()
        return row_id

    def get_skill(self, skill_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a task skill."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, name, steps, tags, file_path, created_at, updated_at
            FROM task_skills WHERE id = ?
        """, (skill_id,))

        row = cursor.fetchone()
        if row:
            data = dict(row)
            # Load full content from file if available
            if data.get("file_path"):
                try:
                    file_path = Path(data["file_path"])
                    if file_path.exists():
                        data["full_steps"] = file_path.read_text(encoding="utf-8")
                        data["file_path"] = str(file_path)
                except Exception:
                    pass
            return data
        return None

    def list_skills(self, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all task skills, optionally filtered by tag."""
        cursor = self.db.cursor()

        if tag:
            cursor.execute("""
                SELECT id, name, tags, file_path, created_at
                FROM task_skills
                WHERE tags LIKE ?
                ORDER BY updated_at DESC
            """, (f"%{tag}%",))
        else:
            cursor.execute("""
                SELECT id, name, tags, file_path, created_at
                FROM task_skills
                ORDER BY updated_at DESC
            """)

        return [dict(row) for row in cursor.fetchall()]

    # ============ CLEANUP ============

    def cleanup_expired_context(self) -> int:
        """Remove expired short-lived context. Returns count deleted."""
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM short_lived_context
            WHERE expires_at IS NOT NULL AND expires_at < datetime('now')
        """)
        self.db.commit()
        return cursor.rowcount

    def cleanup_retention(self, retention_days: int = RETENTION_DAYS) -> int:
        """Delete transient records outside the retention window."""
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM short_lived_context
            WHERE created_at < datetime('now', ?)
        """, (f"-{retention_days} days",))
        self.db.commit()
        return cursor.rowcount

    def promote_eligible_context(self) -> int:
        """Promote frequently accessed or fixed lessons into durable OKF files."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, title, content, lesson, embedding
            FROM short_lived_context
            WHERE access_count >= ? OR fixed_lesson = 1
        """, (PROMOTION_ACCESS_THRESHOLD,))
        rows = cursor.fetchall()
        promoted = 0
        for row in rows:
            category = "lessons"
            content = self._to_okf(row["title"], row["content"], row["lesson"])
            existing = self._similar_durable(row["embedding"])
            if existing:
                path = Path(existing["file_path"]) if existing["file_path"] else None
                current = path.read_text(encoding="utf-8") if path and path.exists() else existing["content"]
                if content not in current:
                    updated = current.rstrip() + "\n\n" + content + "\n"
                    if path:
                        path.write_text(updated, encoding="utf-8")
                    cursor.execute(
                        "UPDATE durable_knowledge SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (updated[-500:], existing["id"]),
                    )
                    cursor.execute("DELETE FROM fts_durable_knowledge WHERE rowid = ?", (existing["id"],))
                    cursor.execute("""
                        INSERT INTO fts_durable_knowledge (rowid, title, content, category)
                        SELECT id, title, content, category FROM durable_knowledge WHERE id = ?
                    """, (existing["id"],))
            else:
                filepath = KNOWLEDGE_DIR / f"{category}_{row['title'].replace(' ', '_').lower()}.md"
                filepath.write_text(content, encoding="utf-8")
                cursor.execute("""
                    INSERT INTO durable_knowledge
                        (title, content, category, file_path, embedding)
                    VALUES (?, ?, ?, ?, ?)
                """, (row["title"], content[:500], category, str(filepath), row["embedding"]))
                durable_id = cursor.lastrowid
                cursor.execute("""
                    INSERT INTO fts_durable_knowledge (rowid, title, content, category)
                    VALUES (?, ?, ?, ?)
                """, (durable_id, row["title"], content[:500], category))
            cursor.execute("DELETE FROM fts_short_lived_context WHERE rowid = ?", (row["id"],))
            cursor.execute("DELETE FROM short_lived_context WHERE id = ?", (row["id"],))
            promoted += 1
        self.db.commit()
        return promoted

    def _similar_durable(self, embedding_blob: bytes) -> Optional[Dict[str, Any]]:
        if not embedding_blob:
            return None
        import numpy as np
        source = np.frombuffer(embedding_blob, dtype=np.float32)
        cursor = self.db.cursor()
        cursor.execute("SELECT id, content, file_path, embedding FROM durable_knowledge")
        best = None
        best_score = 0.0
        for row in cursor.fetchall():
            if not row["embedding"]:
                continue
            target = np.frombuffer(row["embedding"], dtype=np.float32)
            score = float(np.dot(source, target) / (np.linalg.norm(source) * np.linalg.norm(target) + 1e-10))
            if score > best_score:
                best_score, best = score, dict(row)
        return best if best_score >= PROMOTION_SIMILARITY_THRESHOLD else None

    @staticmethod
    def _to_okf(title: str, content: str, lesson: Optional[str]) -> str:
        return (
            f"---\ntitle: {title}\ntype: lesson\n---\n\n"
            f"# {title}\n\n## Finding\n{content}\n\n"
            f"## Actionable Rule\n- {lesson or content}\n"
        )
