"""Configuration for Agentic Memory MCP."""
import os
from pathlib import Path
from typing import Optional

# Database and directory locations (configurable via environment variables)
DB_PATH = Path(os.environ.get("AGENTIC_MEMORY_DB", Path.home() / ".copilot" / "agentic_memory.db"))
KNOWLEDGE_DIR = Path(os.environ.get("AGENTIC_MEMORY_KNOWLEDGE_DIR", DB_PATH.parent / "knowledge"))
SKILLS_DIR = Path(os.environ.get("AGENTIC_MEMORY_SKILLS_DIR", DB_PATH.parent / "skills"))

# Embedding model settings
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
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
    "Use recall once for relevant non-trivial work; results are compact by default. "
    "Write memory only for a reusable lesson supported by verified tests/builds, "
    "tool results, PR outcomes, or explicit user feedback. Report outcomes only "
    "for recalled memories actually used and causally related to the evidence. "
    "No signal or reusable lesson means no memory write. Never store secrets, "
    "credentials, private data, raw logs, or machine-specific paths."
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
