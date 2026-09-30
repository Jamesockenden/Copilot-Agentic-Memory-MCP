"""Memory storage and retrieval operations."""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import json
import hashlib
import math
import os
import re

from embeddings import extract_file_references, get_embedding
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

    def store_okf(
        self,
        title: str,
        content: str,
        category: str,
        working_directory: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> int:
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
        self._save_scope("durable_knowledge", row_id, content, working_directory, branch)

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
            data["memory_id"] = f"durable_knowledge:{doc_id}"
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
        memory_kind: str = "rule",
        working_directory: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> int:
        """Store Short-Lived Context (episodic notes) directly in DB."""
        embedding = get_embedding(content)
        embedding_bytes = embedding.tobytes()
        expires_at = datetime.now() + timedelta(days=ttl_days)

        cursor = self.db.cursor()
        pattern_hash = hashlib.sha256(" ".join(content.lower().split()).encode()).hexdigest()
        cursor.execute("""
            INSERT INTO short_lived_context
                (title, content, lesson, embedding, expires_at, pattern_hash, memory_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, content, lesson, embedding_bytes, expires_at, pattern_hash, memory_kind))

        # Update FTS index
        row_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO fts_short_lived_context (rowid, title, content, lesson)
            VALUES (?, ?, ?, ?)
        """, (row_id, title, content, lesson or ""))
        self._save_scope("short_lived_context", row_id, f"{title}\n{content}\n{lesson or ''}", working_directory, branch)

        self.db.commit()
        return row_id

    def get_context(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a context note."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, title, content, lesson, created_at, expires_at,
                   access_count, last_accessed_at, pattern_hash, fixed_lesson, memory_kind
            FROM short_lived_context WHERE id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))
        """, (doc_id,))

        row = cursor.fetchone()
        if row:
            data = dict(row)
            data["memory_id"] = f"short_lived_context:{doc_id}"
            cursor.execute("""
                UPDATE short_lived_context
                SET access_count = access_count + 1, last_accessed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (doc_id,))
            self.db.commit()
            return data
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

    def store_skill(
        self,
        name: str,
        steps: str,
        tags: Optional[str] = None,
        working_directory: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> int:
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
        self._save_scope("task_skills", row_id, f"{name}\n{steps}\n{tags or ''}", working_directory, branch)
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
            data["memory_id"] = f"task_skills:{skill_id}"
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

    def record_outcome(
        self,
        memory_ids_used: List[str],
        outcome: str,
        signal: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record evidence for memories explicitly reported as used."""
        if outcome not in {"success", "failure", "user_corrected"}:
            raise ValueError("outcome must be success, failure, or user_corrected")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", signal or ""):
            raise ValueError(
                "signal must be a short identifier (letters, digits, '.', '_' or '-')"
            )

        updated = []
        anti_patterns = []
        session_hash = (
            hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            if session_id else None
        )
        for reference in dict.fromkeys(memory_ids_used):
            memory_type, memory_id = self._resolve_memory_id(reference)
            cursor = self.db.cursor()
            cursor.execute(
                f"SELECT id FROM {memory_type} WHERE id = ?", (memory_id,)
            )
            if not cursor.fetchone():
                raise ValueError(f"Memory {reference!r} does not exist")

            cursor.execute("""
                INSERT INTO memory_feedback
                    (memory_type, memory_id, outcome, signal, session_id)
                VALUES (?, ?, ?, ?, ?)
            """, (memory_type, memory_id, outcome, signal, session_hash))
            cursor.execute("""
                INSERT INTO memory_metrics
                    (memory_type, memory_id, total_uses, successes, failures, corrections,
                     success_streak, last_used_at, last_success_at)
                VALUES (?, ?, 1, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                        CASE WHEN ? = 'success' THEN CURRENT_TIMESTAMP END)
                ON CONFLICT(memory_type, memory_id) DO UPDATE SET
                    total_uses = total_uses + 1,
                    successes = successes + excluded.successes,
                    failures = failures + excluded.failures,
                    corrections = corrections + excluded.corrections,
                    success_streak = CASE
                        WHEN ? = 'success' THEN success_streak + 1 ELSE 0 END,
                    last_used_at = CURRENT_TIMESTAMP,
                    last_success_at = CASE WHEN ? = 'success'
                        THEN CURRENT_TIMESTAMP ELSE last_success_at END
            """, (
                memory_type, memory_id,
                int(outcome == "success"), int(outcome == "failure"),
                int(outcome == "user_corrected"), int(outcome == "success"),
                outcome, outcome, outcome,
            ))
            cursor.execute("""
                SELECT total_uses, successes, failures, corrections, success_streak
                FROM memory_metrics WHERE memory_type = ? AND memory_id = ?
            """, (memory_type, memory_id))
            metric = dict(cursor.fetchone())

            if memory_type == "short_lived_context":
                cursor.execute("""
                    UPDATE short_lived_context SET consecutive_successes = ?
                    WHERE id = ?
                """, (metric["success_streak"], memory_id))
                if metric["success_streak"] >= 3:
                    self.promote_eligible_context()
            if outcome == "failure" and session_hash:
                anti_pattern_id = self._capture_repeated_failure(
                    memory_type, memory_id, signal
                )
                if anti_pattern_id:
                    anti_patterns.append(anti_pattern_id)

            updated.append({
                "memory_id": f"{memory_type}:{memory_id}",
                **metric,
            })
        self.db.commit()
        return {"updated": updated, "anti_pattern_context_ids": anti_patterns}

    def _resolve_memory_id(self, reference: str) -> tuple[str, int]:
        """Resolve a tier-qualified reference, or an unambiguous legacy mem_N ID."""
        types = {"durable_knowledge", "short_lived_context", "task_skills"}
        if ":" in reference:
            memory_type, raw_id = reference.rsplit(":", 1)
            if memory_type not in types or not raw_id.isdigit():
                raise ValueError(f"Invalid memory ID {reference!r}; use tier:id")
            return memory_type, int(raw_id)

        if reference.startswith("mem_") and reference[4:].isdigit():
            memory_id = int(reference[4:])
            matches = []
            for memory_type in types:
                if self.db.execute(
                    f"SELECT 1 FROM {memory_type} WHERE id = ?", (memory_id,)
                ).fetchone():
                    matches.append(memory_type)
            if len(matches) == 1:
                return matches[0], memory_id
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous memory ID {reference!r}; use tier-qualified ID from recall"
                )
        raise ValueError(f"Invalid memory ID {reference!r}; use tier:id")

    def _capture_repeated_failure(
        self, memory_type: str, memory_id: int, signal: str
    ) -> Optional[int]:
        """Create a provisional anti-pattern only after failures in three sessions."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT COUNT(DISTINCT session_id) FROM memory_feedback
            WHERE memory_type = ? AND memory_id = ? AND outcome = 'failure'
              AND session_id IS NOT NULL
        """, (memory_type, memory_id))
        if cursor.fetchone()[0] < 3:
            return None

        cursor.execute(
            f"SELECT title, content FROM {memory_type} WHERE id = ?", (memory_id,)
        )
        source = cursor.fetchone()
        if not source:
            return None
        if memory_type == "short_lived_context":
            cursor.execute(
                "SELECT memory_kind FROM short_lived_context WHERE id = ?", (memory_id,)
            )
            if cursor.fetchone()["memory_kind"] == "anti_pattern":
                return None
        marker = f"Source memory: {memory_type}:{memory_id}"
        cursor.execute("""
            SELECT id FROM short_lived_context
            WHERE memory_kind = 'anti_pattern' AND content LIKE ?
            LIMIT 1
        """, (f"%{marker}%",))
        existing = cursor.fetchone()
        if existing:
            return None

        content = (
            f"Provisional anti-pattern based on failures reported in at least three "
            f"independent sessions while using the cited memory. Review before treating "
            f"this as a confirmed rule.\n\n{marker}\n"
            f"Original memory: {source['title']}\n"
            f"Reported signal: {signal}\n\n{source['content']}"
        )
        return self.store_context(
            f"Potential anti-pattern: {source['title']}",
            content,
            lesson="Review the repeated failures and verify causality before relying on this warning.",
            ttl_days=90,
            memory_kind="anti_pattern",
        )

    def _save_scope(
        self,
        memory_type: str,
        memory_id: int,
        text: str,
        working_directory: Optional[str],
        branch: Optional[str],
    ) -> None:
        root_fingerprint = None
        if working_directory:
            normalized_root = os.path.normcase(os.path.realpath(working_directory))
            root_fingerprint = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()
        paths = extract_file_references(text)
        self.db.execute("""
            INSERT INTO memory_scope
                (memory_type, memory_id, working_directory, branch, file_paths)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(memory_type, memory_id) DO UPDATE SET
                working_directory = excluded.working_directory,
                branch = excluded.branch,
                file_paths = excluded.file_paths,
                stale = 0
        """, (memory_type, memory_id, root_fingerprint, branch, json.dumps(paths)))

    # ============ CLEANUP ============

    def cleanup_expired_context(self) -> int:
        """Remove expired short-lived context. Returns count deleted."""
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM short_lived_context
            WHERE expires_at IS NOT NULL AND expires_at < datetime('now')
        """)
        cursor.execute("""
            DELETE FROM memory_scope
            WHERE memory_type = 'short_lived_context'
              AND memory_id NOT IN (SELECT id FROM short_lived_context)
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
        cursor.execute("""
            DELETE FROM memory_scope
            WHERE memory_type = 'short_lived_context'
              AND memory_id NOT IN (SELECT id FROM short_lived_context)
        """)
        self.db.commit()
        return cursor.rowcount

    def promote_eligible_context(self) -> int:
        """Promote frequently accessed or fixed lessons into durable OKF files."""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT id, title, content, lesson, embedding, memory_kind
            FROM short_lived_context
            WHERE (memory_kind != 'anti_pattern' AND
                   (access_count >= ? OR consecutive_successes >= 3))
               OR fixed_lesson = 1
        """, (PROMOTION_ACCESS_THRESHOLD,))
        rows = cursor.fetchall()
        promoted = 0
        for row in rows:
            category = "lessons"
            content = self._to_okf(row["title"], row["content"], row["lesson"])
            existing = self._similar_durable(row["embedding"])
            if existing:
                durable_id = existing["id"]
                path = Path(existing["file_path"]) if existing["file_path"] else None
                current = path.read_text(encoding="utf-8") if path and path.exists() else existing["content"]
                if content not in current:
                    updated = current.rstrip() + "\n\n" + content + "\n"
                    if path:
                        path.write_text(updated, encoding="utf-8")
                    embedding = get_embedding(updated).tobytes()
                    cursor.execute(
                        "UPDATE durable_knowledge SET content = ?, embedding = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (updated[:500], embedding, existing["id"]),
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
            cursor.execute("""
                INSERT INTO memory_scope
                    (memory_type, memory_id, working_directory, branch, file_paths)
                SELECT 'durable_knowledge', ?, working_directory, branch, file_paths
                FROM memory_scope
                WHERE memory_type = 'short_lived_context' AND memory_id = ?
                ON CONFLICT(memory_type, memory_id) DO NOTHING
            """, (durable_id, row["id"]))
            cursor.execute("""
                INSERT INTO memory_metrics
                    (memory_type, memory_id, total_uses, successes, failures, corrections,
                     success_streak, last_used_at, last_success_at)
                SELECT 'durable_knowledge', ?, total_uses, successes, failures, corrections,
                       success_streak, last_used_at, last_success_at
                FROM memory_metrics
                WHERE memory_type = 'short_lived_context' AND memory_id = ?
                ON CONFLICT(memory_type, memory_id) DO UPDATE SET
                    total_uses = total_uses + excluded.total_uses,
                    successes = successes + excluded.successes,
                    failures = failures + excluded.failures,
                    corrections = corrections + excluded.corrections,
                    success_streak = MAX(success_streak, excluded.success_streak),
                    last_used_at = MAX(last_used_at, excluded.last_used_at),
                    last_success_at = MAX(last_success_at, excluded.last_success_at)
            """, (durable_id, row["id"]))
            cursor.execute("""
                UPDATE memory_feedback SET memory_type = 'durable_knowledge', memory_id = ?
                WHERE memory_type = 'short_lived_context' AND memory_id = ?
            """, (durable_id, row["id"]))
            cursor.execute("""
                SELECT working_directory, branch, file_paths FROM memory_scope
                WHERE memory_type = 'short_lived_context' AND memory_id = ?
            """, (row["id"],))
            source_scope = cursor.fetchone()
            cursor.execute("""
                SELECT working_directory, branch, file_paths FROM memory_scope
                WHERE memory_type = 'durable_knowledge' AND memory_id = ?
            """, (durable_id,))
            durable_scope = cursor.fetchone()
            if source_scope:
                source_paths = json.loads(source_scope["file_paths"] or "[]")
                durable_paths = (
                    json.loads(durable_scope["file_paths"] or "[]")
                    if durable_scope else []
                )
                merged_paths = list(dict.fromkeys(durable_paths + source_paths))
                cursor.execute("""
                    INSERT INTO memory_scope
                        (memory_type, memory_id, working_directory, branch, file_paths)
                    VALUES ('durable_knowledge', ?, ?, ?, ?)
                    ON CONFLICT(memory_type, memory_id) DO UPDATE SET
                        working_directory = COALESCE(memory_scope.working_directory, excluded.working_directory),
                        branch = COALESCE(memory_scope.branch, excluded.branch),
                        file_paths = excluded.file_paths,
                        stale = 0
                """, (
                    durable_id,
                    (durable_scope["working_directory"] if durable_scope else None)
                    or source_scope["working_directory"],
                    (durable_scope["branch"] if durable_scope else None)
                    or source_scope["branch"],
                    json.dumps(merged_paths),
                ))
            cursor.execute("""
                DELETE FROM memory_metrics
                WHERE memory_type = 'short_lived_context' AND memory_id = ?
            """, (row["id"],))
            cursor.execute("DELETE FROM fts_short_lived_context WHERE rowid = ?", (row["id"],))
            cursor.execute(
                "DELETE FROM memory_scope WHERE memory_type = 'short_lived_context' AND memory_id = ?",
                (row["id"],),
            )
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
