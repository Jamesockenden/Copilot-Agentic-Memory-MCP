"""Configuration for Agentic Memory MCP."""
import os
from pathlib import Path
from typing import Optional

# Database and directory locations (configurable via environment variables)
DB_PATH = Path(os.environ.get("AGENTIC_MEMORY_DB", Path.home() / ".copilot" / "agentic_memory.db"))
KNOWLEDGE_DIR = Path(os.environ.get("AGENTIC_MEMORY_KNOWLEDGE_DIR", DB_PATH.parent / "knowledge"))
SKILLS_DIR = Path(os.environ.get("AGENTIC_MEMORY_SKILLS_DIR", DB_PATH.parent / "skills"))

# Embedding model settings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Lightweight, fast model
EMBEDDING_DIM = 384

# Default TTL for short-lived context (days)
DEFAULT_CONTEXT_TTL = 30
RETENTION_DAYS = 14
SHORT_LIVED_SEARCH_WINDOW_HOURS = 48
SHORT_LIVED_TIER_WEIGHT = 0.5
DURABLE_TIER_WEIGHT = 1.0
DECAY_LAMBDA = 0.1
PROMOTION_ACCESS_THRESHOLD = 3
PROMOTION_SIMILARITY_THRESHOLD = 0.85

# RRF parameters
RRF_K = 60  # Parameter for reciprocal rank fusion

# Search parameters
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 20

# Memory store settings
ENABLE_CLEANUP = True  # Auto-cleanup expired context
CLEANUP_INTERVAL_HOURS = 24
AUTO_LEARNING_ENABLED = True
AUTO_LEARNING_TTL_DAYS = DEFAULT_CONTEXT_TTL
AUTO_LEARNING_INSTRUCTION = (
    "When a task reveals a reusable fix, decision, constraint, or workflow, "
    "call the agentic-memory learn tool before completing the response. "
    "Do not save secrets, credentials, or user-specific ephemeral details."
)

# Logging
LOG_LEVEL = "INFO"
LOG_PATH = Path(os.environ.get("AGENTIC_MEMORY_LOG", DB_PATH.parent / "agentic_memory.log"))

def ensure_paths():
    """Ensure required directories exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
