"""Tests for Agentic Memory MCP server."""
import tempfile
import sqlite3
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from database import init_db
from memory_store import MemoryStore
from embeddings import hybrid_search, fts_search, vector_search


def test_database_init():
    """Test database initialization."""
    db_path = Path.home() / ".copilot" / "test_db.sqlite"
    try:
        db = sqlite3.connect(str(db_path))

        # Run schema creation
        cursor = db.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS durable_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                embedding BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_durable_knowledge
            USING fts5(title, content, category, content=durable_knowledge, content_rowid=id)
        """)

        db.commit()
        db.close()

        # Verify tables exist
        db = sqlite3.connect(str(db_path))
        cursor = db.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='durable_knowledge'")
        assert cursor.fetchone() is not None, "durable_knowledge table not created"
        db.close()

        print("[PASS] Database initialization test passed")
    finally:
        if db_path.exists():
            db_path.unlink()


def test_okf_storage():
    """Test storing and retrieving OKF documents."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    # Minimal schema for testing
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE durable_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, content TEXT, category TEXT, file_path TEXT, embedding BLOB,
            created_at TIMESTAMP, updated_at TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE VIRTUAL TABLE fts_durable_knowledge
        USING fts5(title, content, category, content=durable_knowledge, content_rowid=id)
    """)
    db.commit()

    store = MemoryStore(db)

    # Store a document
    doc_id = store.store_okf(
        "Authentication Architecture",
        "# JWT Auth\n\nJWT tokens expire after 24 hours",
        "architecture"
    )

    assert doc_id > 0, "Document ID should be positive"

    # Retrieve it
    doc = store.get_durable_knowledge(doc_id)
    assert doc is not None, "Document should be retrievable"
    assert doc["title"] == "Authentication Architecture"
    assert doc["category"] == "architecture"

    db.close()
    print("[PASS] OKF storage test passed")


def test_context_storage():
    """Test storing and retrieving context notes."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    # Minimal schema
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE short_lived_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, content TEXT, lesson TEXT, embedding BLOB,
            created_at TIMESTAMP, expires_at TIMESTAMP,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TIMESTAMP, pattern_hash TEXT,
            fixed_lesson INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE VIRTUAL TABLE fts_short_lived_context
        USING fts5(title, content, lesson, content=short_lived_context, content_rowid=id)
    """)
    db.commit()

    store = MemoryStore(db)

    # Store a note
    note_id = store.store_context(
        "Database Migration Issue",
        "Encountered foreign key constraint error during migration",
        lesson="Always backup before migrations"
    )

    assert note_id > 0, "Note ID should be positive"

    # Retrieve it
    note = store.get_context(note_id)
    assert note is not None, "Note should be retrievable"
    assert note["lesson"] == "Always backup before migrations"

    db.close()
    print("[PASS] Context storage test passed")


def test_skill_storage():
    """Test storing and retrieving task skills."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    # Minimal schema
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE task_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            steps TEXT, tags TEXT, file_path TEXT, embedding BLOB,
            created_at TIMESTAMP, updated_at TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE VIRTUAL TABLE fts_task_skills
        USING fts5(name, steps, tags, content=task_skills, content_rowid=id)
    """)
    db.commit()

    store = MemoryStore(db)

    # Store a skill
    skill_id = store.store_skill(
        "Deploy to Production",
        "1. Run tests\n2. Build\n3. Deploy",
        tags="deployment,production"
    )

    assert skill_id > 0, "Skill ID should be positive"

    # Retrieve it
    skill = store.get_skill(skill_id)
    assert skill is not None, "Skill should be retrievable"
    assert "Deploy to Production" in skill["name"]

    db.close()
    print("[PASS] Skill storage test passed")


def test_embeddings():
    """Test embedding generation."""
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
    assert len(emb1) > 0, "Should have dimensions"

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

        print("\n[PASS] All tests passed!")
    except AssertionError as e:
        print(f"\n[FAIL] Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
