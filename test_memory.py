"""Tests for Agentic Memory MCP server."""
import tempfile
import sqlite3
from pathlib import Path
import sys
from contextlib import contextmanager

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import database as database_module
from database import init_db
import embeddings as embeddings_module
import memory_store as memory_store_module
from memory_store import MemoryStore
from embeddings import (
    _citations_exist,
    extract_file_references,
    hybrid_search,
    fts_search,
    reciprocal_rank_fusion,
    vector_search,
)


@contextmanager
def _test_store():
    """Create a complete isolated schema and temporary memory directories."""
    import numpy as np

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    cursor.executescript("""
        CREATE TABLE durable_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT,
            category TEXT NOT NULL, file_path TEXT, embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE VIRTUAL TABLE fts_durable_knowledge USING fts5(
            title, content, category, content=durable_knowledge, content_rowid=id
        );
        CREATE TABLE short_lived_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL,
            lesson TEXT, embedding BLOB, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP, access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TIMESTAMP, pattern_hash TEXT,
            fixed_lesson INTEGER NOT NULL DEFAULT 0, memory_kind TEXT NOT NULL DEFAULT 'rule',
            consecutive_successes INTEGER NOT NULL DEFAULT 0
        );
        CREATE VIRTUAL TABLE fts_short_lived_context USING fts5(
            title, content, lesson, content=short_lived_context, content_rowid=id
        );
        CREATE TABLE task_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, steps TEXT,
            tags TEXT, file_path TEXT, embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE VIRTUAL TABLE fts_task_skills USING fts5(
            name, steps, tags, content=task_skills, content_rowid=id
        );
        CREATE TABLE memory_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, memory_type TEXT NOT NULL,
            memory_id INTEGER NOT NULL, outcome TEXT NOT NULL, signal TEXT NOT NULL,
            session_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE memory_metrics (
            memory_type TEXT NOT NULL, memory_id INTEGER NOT NULL,
            total_uses INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0, corrections INTEGER NOT NULL DEFAULT 0,
            success_streak INTEGER NOT NULL DEFAULT 0, last_used_at TIMESTAMP,
            last_success_at TIMESTAMP, PRIMARY KEY (memory_type, memory_id)
        );
        CREATE TABLE memory_scope (
            memory_type TEXT NOT NULL, memory_id INTEGER NOT NULL,
            working_directory TEXT, branch TEXT, file_paths TEXT NOT NULL DEFAULT '[]',
            stale INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (memory_type, memory_id)
        );
    """)
    old_knowledge_dir = memory_store_module.KNOWLEDGE_DIR
    old_skills_dir = memory_store_module.SKILLS_DIR
    old_embedding = memory_store_module.get_embedding
    with tempfile.TemporaryDirectory() as temp_dir:
        memory_store_module.KNOWLEDGE_DIR = Path(temp_dir) / "knowledge"
        memory_store_module.SKILLS_DIR = Path(temp_dir) / "skills"
        memory_store_module.KNOWLEDGE_DIR.mkdir()
        memory_store_module.SKILLS_DIR.mkdir()
        memory_store_module.get_embedding = lambda _text: np.ones(384, dtype=np.float32)
        try:
            yield MemoryStore(db)
        finally:
            db.close()
            memory_store_module.KNOWLEDGE_DIR = old_knowledge_dir
            memory_store_module.SKILLS_DIR = old_skills_dir
            memory_store_module.get_embedding = old_embedding


def test_database_init():
    """Test schema creation and repeatable migrations in an isolated database."""
    with tempfile.TemporaryDirectory() as temp_dir:
        original_path = database_module.DB_PATH
        database_module.DB_PATH = Path(temp_dir) / "test_db.sqlite"
        try:
            legacy_db = sqlite3.connect(str(database_module.DB_PATH))
            legacy_db.execute("""
                CREATE TABLE short_lived_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    content TEXT NOT NULL, lesson TEXT, embedding BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMP
                )
            """)
            legacy_db.close()
            db = init_db()
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(short_lived_context)")
            }
            assert {"memory_kind", "consecutive_successes"} <= columns
            tables = {
                row["name"] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert {"memory_feedback", "memory_metrics", "memory_scope"} <= tables
            db.close()
            db = init_db()
            db.close()
            print("[PASS] Database initialization test passed")
        finally:
            database_module.DB_PATH = original_path


def test_okf_storage():
    """Test storing and retrieving OKF documents."""
    with _test_store() as store:
        doc_id = store.store_okf(
            "Authentication Architecture",
            "# JWT Auth\n\nJWT tokens expire after 24 hours",
            "architecture"
        )
        assert doc_id > 0, "Document ID should be positive"
        doc = store.get_durable_knowledge(doc_id)
        assert doc is not None, "Document should be retrievable"
        assert doc["title"] == "Authentication Architecture"
        assert doc["category"] == "architecture"
        assert doc["memory_id"] == f"durable_knowledge:{doc_id}"

    print("[PASS] OKF storage test passed")


def test_context_storage():
    """Test storing and retrieving context notes."""
    with _test_store() as store:
        note_id = store.store_context(
            "Database Migration Issue",
            "Encountered foreign key constraint error during migration",
            lesson="Always backup before migrations"
        )
        assert note_id > 0, "Note ID should be positive"
        note = store.get_context(note_id)
        assert note is not None, "Note should be retrievable"
        assert note["lesson"] == "Always backup before migrations"
        assert note["memory_id"] == f"short_lived_context:{note_id}"

    print("[PASS] Context storage test passed")


def test_skill_storage():
    """Test storing and retrieving task skills."""
    with _test_store() as store:
        skill_id = store.store_skill(
            "Deploy to Production",
            "1. Run tests\n2. Build\n3. Deploy",
            tags="deployment,production"
        )
        assert skill_id > 0, "Skill ID should be positive"
        skill = store.get_skill(skill_id)
        assert skill is not None, "Skill should be retrievable"
        assert "Deploy to Production" in skill["name"]
        assert skill["memory_id"] == f"task_skills:{skill_id}"

    print("[PASS] Skill storage test passed")


def test_outcome_feedback_and_promotion():
    """Successful outcomes reinforce context and promote after three in a row."""
    with _test_store() as store:
        context_id = store.store_context(
            "Stable testing workflow",
            "Run the focused test suite before the full build.",
        )
        for _ in range(3):
            result = store.record_outcome(
                [f"short_lived_context:{context_id}"], "success", "unit_test_passed"
            )
        assert result["updated"][0]["success_streak"] == 3
        assert store.db.execute(
            "SELECT COUNT(*) FROM short_lived_context WHERE id = ?", (context_id,)
        ).fetchone()[0] == 0
        assert store.db.execute(
            "SELECT COUNT(*) FROM durable_knowledge WHERE title = 'Stable testing workflow'"
        ).fetchone()[0] == 1
        metrics = store.db.execute(
            "SELECT total_uses, successes, success_streak FROM memory_metrics "
            "WHERE memory_type = 'durable_knowledge'"
        ).fetchone()
        assert tuple(metrics) == (3, 3, 3)
    print("[PASS] Outcome feedback and promotion test passed")


def test_failure_feedback_is_cautious_and_captures_repeated_pattern():
    """One failure is reversible; only three distinct sessions create a provisional warning."""
    with _test_store() as store:
        context_id = store.store_context("Risky recommendation", "Use the legacy migration path.")
        reference = f"short_lived_context:{context_id}"
        store.record_outcome([reference], "failure", "build_failed", "session-one")
        assert store.db.execute(
            "SELECT COUNT(*) FROM short_lived_context WHERE memory_kind = 'anti_pattern'"
        ).fetchone()[0] == 0
        store.record_outcome([reference], "failure", "build_failed", "session-two")
        result = store.record_outcome([reference], "failure", "build_failed", "session-three")
        assert len(result["anti_pattern_context_ids"]) == 1
        assert store.db.execute(
            "SELECT COUNT(*) FROM short_lived_context WHERE memory_kind = 'anti_pattern'"
        ).fetchone()[0] == 1
        metrics = store.db.execute(
            "SELECT total_uses, failures, success_streak FROM memory_metrics "
            "WHERE memory_type = 'short_lived_context' AND memory_id = ?",
            (context_id,),
        ).fetchone()
        assert tuple(metrics) == (3, 3, 0)
    print("[PASS] Cautious failure feedback test passed")


def test_retrieval_helpers():
    """Exact-query lexical weighting and citation line checks behave as intended."""
    weighted = reciprocal_rank_fusion(
        [(1, 0.9)], [(2, 0.9)], vector_weight=0.2, fts_weight=0.8
    )
    assert weighted[0][0] == 2
    assert extract_file_references("See `src/server.py:2` and C:\\private\\source.py") == [
        "src/server.py:2"
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cited_file = root / "server.py"
        cited_file.write_text("one\ntwo\n", encoding="utf-8")
        assert _citations_exist(root, ["server.py:2"], "")
        assert not _citations_exist(root, ["server.py:3"], "")
        assert not _citations_exist(root, ["..\\outside.py"], "")
    print("[PASS] Retrieval helper tests passed")


def test_compact_recall_payload():
    """Recall defaults to short excerpts and caps opt-in document content."""
    from server import _compact_memory

    long_text = "useful rule " * 500
    document = {
        "memory_id": "durable_knowledge:7",
        "title": "Verified rule",
        "category": "rules",
        "full_content": long_text,
    }
    compact = _compact_memory(document, "durable_knowledge", "content")
    assert compact["memory_id"] == "durable_knowledge:7"
    assert len(compact["excerpt"]) == 400
    assert "content" not in compact
    expanded = _compact_memory(
        document, "durable_knowledge", "content", include_full_content=True
    )
    assert len(expanded["content"]) == 3000
    assert expanded["content_truncated"]
    print("[PASS] Compact recall payload test passed")


def test_scoped_recall_and_stale_citation_suppression():
    """Scoped retrieval verifies file/line citations and suppresses stale memories."""
    import numpy as np

    old_embedding = embeddings_module.get_embedding
    embeddings_module.get_embedding = lambda _text: np.ones(384, dtype=np.float32)
    try:
        with _test_store() as store, tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "src" / "handler.py"
            source.parent.mkdir()
            source.write_text("def first():\n    return True\n", encoding="utf-8")
            context_id = store.store_context(
                "Handler implementation",
                "The handler is described in src/handler.py:2.",
                working_directory=str(root),
                branch="feature/context",
            )
            args = (
                store.db,
                "handler implementation",
                "short_lived_context",
                "fts_short_lived_context",
            )
            assert hybrid_search(
                *args,
                working_directory=str(root),
                branch="feature/context",
                touched_files=["src/handler.py"],
            ) == [context_id]
            source.unlink()
            assert hybrid_search(
                *args,
                working_directory=str(root),
                branch="feature/context",
                touched_files=["src/handler.py"],
            ) == []
            assert store.db.execute(
                "SELECT stale FROM memory_scope WHERE memory_type = 'short_lived_context' AND memory_id = ?",
                (context_id,),
            ).fetchone()[0] == 1
            skill_id = store.store_skill(
                "Handler deployment",
                "Run focused handler tests before deployment.",
                tags="deployment",
            )
            assert hybrid_search(
                store.db,
                "handler deployment",
                "task_skills",
                "fts_task_skills",
            ) == [skill_id]
    finally:
        embeddings_module.get_embedding = old_embedding
    print("[PASS] Scoped and stale-citation retrieval test passed")


def test_embeddings():
    """Test embedding generation."""
    from config import EMBEDDING_DIM, EMBEDDING_MODEL
    from embeddings import get_embedding
    import numpy as np

    # Generate embeddings for similar texts
    text1 = "How do I deploy to production?"
    text2 = "What is the deployment process?"
    text3 = "The weather is nice today"

    emb1 = get_embedding(text1)
    emb2 = get_embedding(text2)
    emb3 = get_embedding(text3)

    assert isinstance(emb1, np.ndarray), "Should return numpy array"
    assert len(emb1) == EMBEDDING_DIM, "Should match configured model dimension"
    assert EMBEDDING_MODEL == "sentence-transformers/all-MiniLM-L6-v2"

    # Similar texts should have higher similarity
    sim_12 = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2) + 1e-10)
    sim_13 = np.dot(emb1, emb3) / (np.linalg.norm(emb1) * np.linalg.norm(emb3) + 1e-10)

    print(f"  Similarity (deployment vs deployment): {sim_12:.3f}")
    print(f"  Similarity (deployment vs weather): {sim_13:.3f}")

    assert sim_12 > sim_13, "Similar texts should have higher similarity"

    print("[PASS] Embeddings test passed")


if __name__ == "__main__":
    print("Running Agentic Memory MCP tests...\n")

    try:
        test_database_init()
        test_embeddings()
        test_okf_storage()
        test_context_storage()
        test_skill_storage()
        test_outcome_feedback_and_promotion()
        test_failure_feedback_is_cautious_and_captures_repeated_pattern()
        test_retrieval_helpers()
        test_compact_recall_payload()
        test_scoped_recall_and_stale_citation_suppression()
        print("\n[PASS] All tests passed!")
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
