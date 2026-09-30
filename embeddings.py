"""Embeddings and vector search functionality."""
import json
import sqlite3
import hashlib
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np
from datetime import datetime
from config import (
    DECAY_LAMBDA,
    DURABLE_TIER_WEIGHT,
    EMBEDDING_MODEL,
    SHORT_LIVED_TIER_WEIGHT,
    SHORT_LIVED_SEARCH_WINDOW_HOURS,
)
_model = None


def get_model():
    """Lazy-load embedding model on first use to ensure instant server startup."""
    global _model
    if _model is None:
        if os.environ.get("AGENTIC_MEMORY_HF_HUB_OFFLINE", "").lower() in {
            "1", "true", "yes", "on"
        }:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_embedding(text: str) -> np.ndarray:
    """Generate embedding for text."""
    return get_model().encode(text, convert_to_numpy=True)


def vector_search(
    db: sqlite3.Connection,
    query: str,
    table: str,
    top_k: int = 5,
) -> List[Tuple[int, float]]:
    """
    Vector search using embeddings.
    Returns: list of (row_id, score) tuples.
    """
    query_embedding = get_embedding(query)
    cursor = db.cursor()

    # Get all embeddings from the table
    cursor.execute(f"SELECT id, embedding FROM {table}")
    results = []

    for row_id, embedding_blob in cursor.fetchall():
        if embedding_blob:
            try:
                embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                # Cosine similarity
                score = float(np.dot(query_embedding, embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(embedding) + 1e-10
                ))
                results.append((row_id, score))
            except Exception:
                continue

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def fts_search(
    db: sqlite3.Connection,
    query: str,
    fts_table: str,
    top_k: int = 5,
) -> List[Tuple[int, float]]:
    """
    Full-text search using FTS5.
    Returns: list of (row_id, rank_score) tuples.
    """
    cursor = db.cursor()

    try:
        cursor.execute(
            f"""
            SELECT rowid, rank FROM {fts_table}
            WHERE {fts_table} MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, top_k)
        )
        return [(row_id, abs(rank)) for row_id, rank in cursor.fetchall()]
    except sqlite3.OperationalError:
        # FTS table may be empty or query invalid
        return []


def reciprocal_rank_fusion(
    vector_results: List[Tuple[int, float]],
    fts_results: List[Tuple[int, float]],
    k: int = 60,
    vector_weight: float = 0.5,
    fts_weight: float = 0.5,
) -> List[Tuple[int, float]]:
    """
    Merge vector and FTS results using Reciprocal Rank Fusion (RRF).
    RRF formula: score = 1 / (k + rank)
    """
    rrf_scores = {}

    # Process vector results
    for rank, (row_id, _score) in enumerate(vector_results, 1):
        rrf_scores[row_id] = rrf_scores.get(row_id, 0) + vector_weight / (k + rank)

    # Process FTS results
    for rank, (row_id, _score) in enumerate(fts_results, 1):
        rrf_scores[row_id] = rrf_scores.get(row_id, 0) + fts_weight / (k + rank)

    # Sort by RRF score descending
    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return merged


def hybrid_search(
    db: sqlite3.Connection,
    query: str,
    table: str,
    fts_table: str,
    top_k: int = 5,
    working_directory: Optional[str] = None,
    branch: Optional[str] = None,
    touched_files: Optional[List[str]] = None,
) -> List[int]:
    """
    Hybrid search combining vector and FTS.
    Returns: list of row_ids in ranked order.
    """
    # Run both searches
    candidate_limit = max(top_k * 5, top_k)
    vector_results = vector_search(db, query, table, top_k=candidate_limit)
    fts_results = fts_search(db, query, fts_table, top_k=candidate_limit)

    # Paths, symbols, identifiers, and error codes benefit from lexical ranking.
    structural_query = bool(
        re.search(r"(?:[/\\]|:\d+|#[Ll]\d+|\b[A-Z]{2,}-\d+\b|\b0x[0-9a-f]+\b)", query)
        or re.search(r"\b[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|cs|cpp|h|sql|yml|yaml|json)\b", query, re.I)
        or re.search(r"\b(?:function|class|symbol|identifier|error|exception|traceback)\b", query, re.I)
    )
    fts_weight, vector_weight = (0.8, 0.2) if structural_query else (0.2, 0.8)
    merged = reciprocal_rank_fusion(
        vector_results,
        fts_results,
        k=60,
        vector_weight=vector_weight,
        fts_weight=fts_weight,
    )

    now = datetime.utcnow()
    if table == "short_lived_context":
        if not merged:
            return []
        cutoff = "datetime('now', ?)"
        filtered = []
        cursor = db.cursor()
        cursor.execute(
            f"SELECT id, created_at FROM {table} WHERE id IN ({','.join('?' for _ in merged)}) "
            f"AND created_at >= {cutoff}",
            [row_id for row_id, _ in merged] + [f"-{SHORT_LIVED_SEARCH_WINDOW_HOURS} hours"],
        )
        ages = {}
        for row in cursor.fetchall():
            if not row[1]:
                continue
            created = datetime.fromisoformat(row[1].replace("Z", "+00:00")).replace(tzinfo=None)
            ages[row[0]] = max(0.0, (now - created).total_seconds() / 86400)
        for rank, (row_id, score) in enumerate(merged, 1):
            if row_id in ages:
                filtered.append((row_id, score * SHORT_LIVED_TIER_WEIGHT * np.exp(-DECAY_LAMBDA * ages[row_id])))
        merged = sorted(filtered, key=lambda item: item[1], reverse=True)
    elif table == "durable_knowledge":
        merged = [(row_id, score * DURABLE_TIER_WEIGHT) for row_id, score in merged]

    if not merged:
        return []

    cursor = db.cursor()
    ids = [row_id for row_id, _score in merged]
    placeholders = ",".join("?" for _ in ids)
    cursor.execute(
        f"SELECT memory_id, working_directory, branch, file_paths, stale "
        f"FROM memory_scope WHERE memory_type = ? AND memory_id IN ({placeholders})",
        [table, *ids],
    )
    scopes = {row["memory_id"]: dict(row) for row in cursor.fetchall()}
    text_column = "steps" if table == "task_skills" else "content"
    title_column = "name" if table == "task_skills" else "title"
    file_column = "NULL" if table == "short_lived_context" else "file_path"
    cursor.execute(
        f"SELECT id, {title_column} AS title, {text_column} AS content, "
        f"created_at, {file_column} AS file_path "
        f"FROM {table} WHERE id IN ({placeholders})",
        ids,
    )
    documents = {row["id"]: dict(row) for row in cursor.fetchall()}
    cursor.execute(
        f"SELECT memory_id, total_uses, successes, last_success_at "
        f"FROM memory_metrics WHERE memory_type = ? AND memory_id IN ({placeholders})",
        [table, *ids],
    )
    metrics = {row["memory_id"]: dict(row) for row in cursor.fetchall()}

    root = Path(working_directory).resolve() if working_directory else None
    touched = {
        os.path.normcase(os.path.normpath(path.replace("/", os.sep)))
        for path in (touched_files or [])
    }
    ranked = []
    for row_id, score in merged:
        scope = scopes.get(row_id, {})
        if scope.get("stale"):
            continue
        stored_root = scope.get("working_directory")
        if stored_root and working_directory:
            current_fingerprint = hashlib.sha256(
                os.path.normcase(os.path.realpath(working_directory)).encode("utf-8")
            ).hexdigest()
            if stored_root != current_fingerprint:
                continue
        if scope.get("branch") and branch and scope["branch"] != branch:
            continue

        try:
            file_paths = json.loads(scope.get("file_paths") or "[]")
        except (TypeError, json.JSONDecodeError):
            file_paths = []
        if touched and file_paths:
            normalized_refs = {
                os.path.normcase(os.path.normpath(item.split(":", 1)[0].replace("/", os.sep)))
                for item in file_paths
            }
            if not touched.intersection(normalized_refs):
                continue

        doc = documents.get(row_id, {})
        cited_text = doc.get("content", "")
        if not file_paths and doc.get("file_path"):
            try:
                cited_text = Path(doc["file_path"]).read_text(encoding="utf-8")
            except OSError:
                pass
        if root and not _citations_exist(root, file_paths, cited_text):
            cursor.execute(
                "INSERT INTO memory_scope (memory_type, memory_id, stale) VALUES (?, ?, 1) "
                "ON CONFLICT(memory_type, memory_id) DO UPDATE SET stale = 1",
                (table, row_id),
            )
            continue

        metric = metrics.get(row_id, {})
        uses = metric.get("total_uses", 0)
        success_rate = (metric.get("successes", 0) + 1) / (uses + 2)
        reference_time = metric.get("last_success_at") or doc.get("created_at")
        age_days = _age_in_days(reference_time, now)
        utility = success_rate * np.exp(-DECAY_LAMBDA * age_days)
        confidence = 1 / (1 + np.exp(-utility))
        ranked.append((row_id, score * confidence))

    db.commit()
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [row_id for row_id, _score in ranked[:top_k]]


_CITATION_PATTERN = re.compile(
    r"(?<![\w./\\:])((?:[\w.-]+[\\/])*[\w.-]+\."
    r"(?:py|ts|tsx|js|jsx|go|rs|java|cs|cpp|h|sql|yml|yaml|json|md))"
    r"(?::L?(\d+)(?:-\d+)?)?",
    re.IGNORECASE,
)


def extract_file_references(text: str) -> List[str]:
    """Extract repository-relative file references, retaining optional line numbers."""
    refs = []
    for match in _CITATION_PATTERN.finditer(text or ""):
        path = match.group(1).replace("\\", "/")
        if not Path(path).is_absolute() and path not in refs:
            refs.append(f"{path}:{match.group(2)}" if match.group(2) else path)
    return refs


def _citations_exist(root: Path, file_paths: List[str], content: str) -> bool:
    references = list(file_paths) or extract_file_references(content)
    for reference in references:
        path_text, separator, line_text = reference.partition(":")
        candidate = (root / path_text).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        if not candidate.is_file():
            return False
        if separator and line_text.isdigit():
            try:
                with candidate.open("r", encoding="utf-8", errors="replace") as cited_file:
                    for current_line, _ in enumerate(cited_file, 1):
                        if current_line >= int(line_text):
                            break
                    else:
                        return False
            except OSError:
                return False
    return True


def _age_in_days(value, now: datetime) -> float:
    if not value:
        return 0.0
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        return max(0.0, (now - timestamp).total_seconds() / 86400)
    except (TypeError, ValueError):
        return 0.0
