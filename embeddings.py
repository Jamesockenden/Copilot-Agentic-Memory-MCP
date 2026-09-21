"""Embeddings and vector search functionality."""
import json
import sqlite3
import hashlib
from typing import List, Tuple
import numpy as np
from datetime import datetime
from config import DECAY_LAMBDA, DURABLE_TIER_WEIGHT, SHORT_LIVED_TIER_WEIGHT, SHORT_LIVED_SEARCH_WINDOW_HOURS
_model = None


def get_model():
    """Lazy-load embedding model on first use to ensure instant server startup."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
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
) -> List[Tuple[int, float]]:
    """
    Merge vector and FTS results using Reciprocal Rank Fusion (RRF).
    RRF formula: score = 1 / (k + rank)
    """
    rrf_scores = {}

    # Process vector results
    for rank, (row_id, _score) in enumerate(vector_results, 1):
        rrf_scores[row_id] = rrf_scores.get(row_id, 0) + 1 / (k + rank)

    # Process FTS results
    for rank, (row_id, _score) in enumerate(fts_results, 1):
        rrf_scores[row_id] = rrf_scores.get(row_id, 0) + 1 / (k + rank)

    # Sort by RRF score descending
    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return merged


def hybrid_search(
    db: sqlite3.Connection,
    query: str,
    table: str,
    fts_table: str,
    top_k: int = 5,
) -> List[int]:
    """
    Hybrid search combining vector and FTS.
    Returns: list of row_ids in ranked order.
    """
    # Run both searches
    vector_results = vector_search(db, query, table, top_k=top_k)
    fts_results = fts_search(db, query, fts_table, top_k=top_k)

    # Merge using RRF
    merged = reciprocal_rank_fusion(vector_results, fts_results, k=60)
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

    # Return top_k row_ids
    return [row_id for row_id, _score in merged[:top_k]]
