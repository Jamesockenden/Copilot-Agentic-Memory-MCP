"""MCP Server implementation supporting both FastMCP (v1) and MCPServer (v2)."""
import atexit
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Optional

# Ensure server's directory is in sys.path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from mcp.server.fastmcp import FastMCP
except (ImportError, ModuleNotFoundError):
    from mcp.server.mcpserver import MCPServer as FastMCP

from database import init_db
from memory_store import MemoryStore
from embeddings import hybrid_search
from config import AUTO_LEARNING_ENABLED, AUTO_LEARNING_TTL_DAYS, ensure_paths

# Initialize MCP server
mcp = FastMCP("agentic-memory")

# Global state
db: Optional[sqlite3.Connection] = None
memory_store: Optional[MemoryStore] = None


def startup():
    """Initialize database and memory store on startup."""
    global db, memory_store
    if db is not None and memory_store is not None:
        return
    ensure_paths()
    db = init_db()
    memory_store = MemoryStore(db)
    try:
        memory_store.cleanup_retention()
        memory_store.cleanup_expired_context()
        memory_store.promote_eligible_context()
        db.execute("PRAGMA incremental_vacuum;")
        db.commit()
    except Exception:
        pass


def shutdown():
    """Clean up on shutdown."""
    global db
    if db:
        if memory_store:
            try:
                memory_store.cleanup_expired_context()
                memory_store.cleanup_retention()
                memory_store.promote_eligible_context()
            except Exception:
                pass
        for attempt in range(4):
            try:
                result = db.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
                if not result or result[0] == 0:
                    break
                if attempt == 3:
                    break
                time.sleep(0.1 * (2 ** attempt))
            except sqlite3.OperationalError as exc:
                if "busy" not in str(exc).lower() or attempt == 3:
                    break
                time.sleep(0.1 * (2 ** attempt))
            except Exception:
                break
        try:
            db.close()
        except Exception:
            pass
        db = None


def ensure_init():
    """Ensure database and memory store are initialized before any tool call."""
    if db is None or memory_store is None:
        startup()


# Register lifecycle handlers if supported by FastMCP v1
if hasattr(mcp, "server") and hasattr(mcp.server, "on_startup"):
    mcp.server.on_startup(startup)
    mcp.server.on_shutdown(shutdown)

atexit.register(shutdown)


# ============ RECALL TOOL ============

@mcp.tool()
def recall(query: str, limit: int = 5) -> str:
    """
    Retrieve relevant memories using hybrid search (vector + FTS + RRF).

    Args:
        query: What you want to remember or find
        limit: Number of results to return (default: 5)

    Returns:
        Ranked list of relevant memories from all three tiers
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    results = {
        "durable_knowledge": [],
        "short_lived_context": [],
        "task_skills": []
    }

    # Search durable knowledge
    try:
        dk_ids = hybrid_search(
            db,
            query,
            "durable_knowledge",
            "fts_durable_knowledge",
            top_k=limit
        )
        for row_id in dk_ids:
            doc = memory_store.get_durable_knowledge(row_id)
            if doc:
                results["durable_knowledge"].append(doc)
    except Exception as e:
        results["durable_knowledge"] = [{"error": str(e)}]

    # Search short-lived context
    try:
        ctx_ids = hybrid_search(
            db,
            query,
            "short_lived_context",
            "fts_short_lived_context",
            top_k=limit
        )
        for row_id in ctx_ids:
            doc = memory_store.get_context(row_id)
            if doc:
                results["short_lived_context"].append(doc)
    except Exception as e:
        results["short_lived_context"] = [{"error": str(e)}]

    # Search task skills
    try:
        skill_ids = hybrid_search(
            db,
            query,
            "task_skills",
            "fts_task_skills",
            top_k=limit
        )
        for row_id in skill_ids:
            skill = memory_store.get_skill(row_id)
            if skill:
                results["task_skills"].append(skill)
    except Exception as e:
        results["task_skills"] = [{"error": str(e)}]

    return str(results)


# ============ STORE TOOLS ============

@mcp.tool()
def store_okf(title: str, content: str, category: str) -> str:
    """
    Store Durable Knowledge in OKF (Objectives & Key Findings) format.
    This is long-term knowledge the agent can rely on.

    Args:
        title: Document title
        content: Markdown formatted content
        category: Category (e.g., "architecture", "api", "rules")

    Returns:
        Confirmation with document ID
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        doc_id = memory_store.store_okf(title, content, category)
        return f"Stored OKF document: {title} (ID: {doc_id})"
    except Exception as e:
        return f"Error storing OKF: {str(e)}"


@mcp.tool()
def store_context(title: str, content: str, lesson: Optional[str] = None, ttl_days: int = 30) -> str:
    """
    Store Short-Lived Context (episodic notes, fixes, lessons).
    These expire after TTL and prevent repeated mistakes.

    Args:
        title: Note title
        content: Description of the issue/fix/lesson
        lesson: Key lesson learned
        ttl_days: Days until expiration (default: 30)

    Returns:
        Confirmation with document ID
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        doc_id = memory_store.store_context(title, content, lesson, ttl_days)
        return f"Stored context note: {title} (ID: {doc_id}, expires in {ttl_days} days)"
    except Exception as e:
        return f"Error storing context: {str(e)}"


@mcp.tool()
def store_skill(name: str, steps: str, tags: Optional[str] = None) -> str:
    """
    Store Task Skill (reusable workflow or procedure).
    Skills are executed consistently across sessions.

    Args:
        name: Skill name (e.g., "Deploy to Production")
        steps: Markdown formatted step-by-step instructions
        tags: Comma-separated tags (e.g., "deployment,production")

    Returns:
        Confirmation with skill ID
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        skill_id = memory_store.store_skill(name, steps, tags)
        return f"Stored skill: {name} (ID: {skill_id})"
    except Exception as e:
        return f"Error storing skill: {str(e)}"


# ============ LEARNING & OBSERVATION TOOLS ============

@mcp.tool()
def learn(observation: str, category: str = "general") -> str:
    """
    Log an observation or lesson from the current session.
    This creates a short-lived context note that helps avoid future mistakes.

    Args:
        observation: What was learned or observed
        category: Category of learning (e.g., "bug-fix", "optimization", "design")

    Returns:
        Confirmation
    """
    if not AUTO_LEARNING_ENABLED:
        return "Automatic learning is disabled"
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        title = f"Lesson: {category}"
        doc_id = memory_store.store_context(
            title, observation, lesson=category, ttl_days=AUTO_LEARNING_TTL_DAYS
        )
        return f"Learning stored (ID: {doc_id}): {observation[:100]}..."
    except Exception as e:
        return f"Error storing learning: {str(e)}"


@mcp.tool()
def mark_lesson_fixed(context_id: int) -> str:
    """Mark a short-lived context note for promotion to durable knowledge."""
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"
    try:
        memory_store.mark_fixed_lesson(context_id)
        return f"Context note {context_id} marked as a fixed lesson"
    except Exception as e:
        return f"Error marking lesson: {str(e)}"


# ============ LIST/BROWSE TOOLS ============

@mcp.tool()
def list_knowledge(category: Optional[str] = None) -> str:
    """
    Browse all stored Durable Knowledge.

    Args:
        category: Optional category filter

    Returns:
        List of knowledge documents
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        docs = memory_store.list_durable_knowledge(category)
        if not docs:
            return "No durable knowledge found"
        return str(docs)
    except Exception as e:
        return f"Error listing knowledge: {str(e)}"


@mcp.tool()
def list_skills(tag: Optional[str] = None) -> str:
    """
    Browse all stored Task Skills.

    Args:
        tag: Optional tag filter

    Returns:
        List of available skills
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        skills = memory_store.list_skills(tag)
        if not skills:
            return "No skills found"
        return str(skills)
    except Exception as e:
        return f"Error listing skills: {str(e)}"


@mcp.tool()
def list_recent_context(limit: int = 10) -> str:
    """
    Browse recent Short-Lived Context notes.

    Args:
        limit: Number of recent notes to return (default: 10)

    Returns:
        List of recent context notes
    """
    ensure_init()
    if not memory_store:
        return "Memory store not initialized"

    try:
        notes = memory_store.list_context(limit)
        if not notes:
            return "No recent context found"
        return str(notes)
    except Exception as e:
        return f"Error listing context: {str(e)}"


if __name__ == "__main__":
    startup()
    if hasattr(mcp, "run"):
        import inspect
        sig = inspect.signature(mcp.run)
        if "transport" in sig.parameters:
            mcp.run(transport="stdio")
        else:
            mcp.run()
