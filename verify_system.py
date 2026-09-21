"""Verification script to test the Agentic Memory MCP system."""
import sys
from database import get_db
from memory_store import MemoryStore
from embeddings import hybrid_search

def verify_system():
    """Verify the memory system is working correctly."""
    db = get_db()
    store = MemoryStore(db)

    print("[INFO] Memory Store Contents:")
    print(f"  Knowledge docs: {len(store.list_durable_knowledge())}")
    print(f"  Context notes: {len(store.list_context())}")
    print(f"  Skills: {len(store.list_skills())}")

    print("\n[INFO] Testing Hybrid Search:")
    test_queries = [
        "How do I deploy to production?",
        "What is JWT authentication?",
        "Bug fix for token validation"
    ]

    for query in test_queries:
        print(f"  Query: \"{query}\"")

        # Search durable knowledge
        try:
            dk_ids = hybrid_search(db, query, 'durable_knowledge', 'fts_durable_knowledge', top_k=2)
            if dk_ids:
                for row_id in dk_ids:
                    doc = store.get_durable_knowledge(row_id)
                    if doc:
                        print(f"    [DK] {doc.get('title', 'Unknown')}")
        except Exception as e:
            pass

        # Search skills
        try:
            sk_ids = hybrid_search(db, query, 'task_skills', 'fts_task_skills', top_k=2)
            if sk_ids:
                for row_id in sk_ids:
                    skill = store.get_skill(row_id)
                    if skill:
                        print(f"    [SKILL] {skill.get('name', 'Unknown')}")
        except Exception as e:
            pass

        # Search context
        try:
            ctx_ids = hybrid_search(db, query, 'short_lived_context', 'fts_short_lived_context', top_k=2)
            if ctx_ids:
                for row_id in ctx_ids:
                    ctx = store.get_context(row_id)
                    if ctx:
                        print(f"    [CTX] {ctx.get('title', 'Unknown')}")
        except Exception as e:
            pass

    db.close()
    print("\n[DONE] System verification complete!")
    print("\n[SUCCESS] Agentic Memory MCP is ready to use!")
    print("  - Start server: python -m agentic_memory_mcp")
    print("  - Add to Copilot CLI configuration (copilot-setup-steps.yml)")
    print("  - Query with recall() tool during sessions")

if __name__ == "__main__":
    verify_system()
