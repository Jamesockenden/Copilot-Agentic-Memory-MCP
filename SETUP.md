# Agentic Memory MCP Setup & Usage Guide

## Installation

### Windows (recommended local setup)

From PowerShell, run the setup script in the project directory:

```powershell
Set-Location "$HOME\.copilot\agentic-memory-mcp"
.\setup-local.ps1
```

The script checks for Python 3.10+, creates an isolated `.venv`, installs the
project requirements there, and loads the embedding model once to verify setup.
The model is `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions); the
first run downloads it from Hugging Face. Model files use the shared Hugging
Face cache, defaulting to `$HOME\.cache\huggingface\hub`. Set `HF_HOME` or
`HF_HUB_CACHE` before running setup if you need a different cache location.
No Hugging Face account or token is required for this public model.

After setup, register the printed command with Copilot CLI. For example:

```powershell
copilot mcp add agentic-memory --tools "*" -- "$HOME\.copilot\agentic-memory-mcp\.venv\Scripts\python.exe" "$HOME\.copilot\agentic-memory-mcp\__main__.py"
```

If the server is already registered, inspect it first with
`copilot mcp get agentic-memory`; use `copilot mcp remove agentic-memory`
before re-adding it to switch its Python command. Confirm the active server
with `copilot mcp list` or the CLI `/mcp` command.

To use the model without network access after setup has downloaded it, register
the server with `--env AGENTIC_MEMORY_HF_HUB_OFFLINE=1`. Hugging Face offline
mode will error if required model files are not cached, so do not enable this
before the warmup succeeds.

### macOS / Linux

```bash
cd ~/.copilot/agentic-memory-mcp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c "from config import EMBEDDING_DIM; from embeddings import get_embedding; assert get_embedding('setup check').shape == (EMBEDDING_DIM,)"
copilot mcp add agentic-memory --tools "*" -- "$PWD/.venv/bin/python" "$PWD/__main__.py"
```

The first embedding check downloads the model to Hugging Face's shared cache.
Set `HF_HOME` or `HF_HUB_CACHE` before launching Copilot to relocate that cache.

### Hugging Face references

- [Model card: all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) documents semantic-search use and its 384-dimensional output.
- [Hugging Face cache management](https://huggingface.co/docs/huggingface_hub/en/guides/manage-cache) describes the shared, revision-aware Hub cache.
- [Hub environment variables](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables) documents `HF_HOME`, `HF_HUB_CACHE`, and `HF_HUB_OFFLINE`.

### Optional Example Data

Only load synthetic examples into a dedicated/test database:

```powershell
.\.venv\Scripts\python.exe examples.py
```

This loads example:
- Durable Knowledge (OKF documents about authentication, API standards)
- Short-Lived Context (recent bug fixes, lessons learned)
- Task Skills (deployment procedures, setup workflows)

---

## Running the MCP Server

### Manual stdio smoke test

Run from a terminal when diagnosing startup; MCP stdio is intended to be
launched by Copilot CLI:

```powershell
.\.venv\Scripts\python.exe __main__.py
```

### Copilot CLI registration

Use `copilot mcp add` as shown in the installation section. This registers a
user-level local stdio server in Copilot CLI's MCP configuration. Do not put
MCP server registration in `copilot-setup-steps.yml`; that file is not the
Copilot CLI MCP configuration.

---

## Using the Memory System

### Recall Information
```
copilot> I need to deploy to production, what are the steps?
```
The MCP server will search all three tiers and return:
- Matching Task Skills (deployment procedures)
- Relevant Durable Knowledge (production standards)
- Recent Context (lessons learned from past deployments)

### Store Knowledge
```
copilot> Save to memory: Our authentication uses JWT tokens that expire after 1 hour
```
Stores in Durable Knowledge tier.

### Record Lessons
```
copilot> Remember: Always run tests before deploying. Found database constraint issue the hard way.
```
Stores in Short-Lived Context tier (expires after 30 days by default).

### Define Workflows
```
copilot> Store workflow: Production deployment requires: test → build → tag → push → deploy
```
Stores in Task Skills tier for consistent execution.

---

## Memory Architecture

### 1. Durable Knowledge (Long-term)
- **Format**: Markdown using Google OKF
- **Retention**: Permanent until manually updated
- **Examples**:
  - Architecture decisions
  - API standards
  - Project rules and conventions
  - Deployment procedures

**Stored at**: `~/.copilot/agentic_memory.db` (table: `durable_knowledge`)

### 2. Short-Lived Context (Episodic)
- **Format**: Markdown notes with lessons
- **Retention**: 30 days by default (configurable)
- **Examples**:
  - Bug fixes and workarounds
  - Optimization insights
  - Error patterns and solutions
  - Session-specific decisions

**Stored at**: `~/.copilot/agentic_memory.db` (table: `short_lived_context`)

### 3. Task Skills (Reusable)
- **Format**: Step-by-step procedures
- **Retention**: Permanent until updated
- **Examples**:
  - Deployment workflows
  - Setup procedures
  - Testing strategies
  - Troubleshooting guides

**Stored at**: `~/.copilot/agentic_memory.db` (table: `task_skills`)

---

## Retrieval Strategy (Hybrid Search)

When you ask a question, the MCP performs:

### 1. Vector Search (Semantic)
- Converts your question to an embedding
- Finds conceptually similar content
- Good for intent-based queries: "How do I deploy?"

### 2. Full-Text Search (Keyword)
- Searches exact keywords, variable names, error codes
- Good for specific lookups: "JWT token", "401 status"

### 3. Reciprocal Rank Fusion (RRF)
- Merges both result sets
- Ranks by relevance across both channels
- Returns top 5 results by default

**Result**: Highly relevant memories without token bloat.

## Feedback learning flow

Treat retrieved memories as candidate strategies to validate through real
execution, not as proof that their advice will work:

1. **Retrieve (forward pass).** The server uses intent-weighted FTS5 and
   embedding ranks, then applies the memory's smoothed outcome utility and
   temporal decay:

   ```text
   utility = ((successes + 1) / (uses + 2)) * exp(-lambda * age)
   score = weighted_RRF * sigmoid(utility)
   ```

   This is a ranking adjustment, not a calibrated probability of task success.
   Use `recall`'s tier-qualified `memory_id` values when reporting outcomes.
   Recall returns short excerpts by default; set `include_full_content=true`
   only when the excerpt is insufficient (returned text is capped).
   Optional `working_directory`, `branch`, and `touched_files` arguments scope
   results; cited repository files and line numbers are checked when a working
   directory is supplied.
2. **Execute and observe.** Use actual tool results and user feedback as the
   outcome signal. A zero exit code confirms command execution, not necessarily
   task correctness; include a correct tool response or user approval when
   relevant. A runtime failure, invalid parameter, hallucinated result, or
   user correction is a failure signal only when evidence ties it to the
   retrieved advice; distinguish this from unrelated environment problems
   such as transient network or dependency outages.
3. **Report evidence.** Call `record_outcome(memory_ids_used, outcome, signal,
   session_id)` with `success`, `failure`, or `user_corrected`. This updates
   relational counters and does not mutate embeddings. Outcome events are
   written synchronously to SQLite; report only externally verified outcomes
   for memories actually used. No ground-truth signal means no memory write.
4. **Consolidate cautiously.** Three consecutive successful outcomes promote
   an episodic lesson to durable OKF. A single failure only lowers the smoothed
   score. A provisional anti-pattern note is created only after failures from
   three distinct supplied session IDs; it remains episodic and should be
   reviewed for causality before promotion.

---

## Configuration

Edit `config.py` to customize:

```python
# Default TTL for short-lived context (days)
DEFAULT_CONTEXT_TTL = 30

# Embedding model (lightweight, fast)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Search result limit
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 20

# RRF fusion parameter
RRF_K = 60
```

---

## Database

The MCP stores all memory in SQLite at: `~/.copilot/agentic_memory.db`

### Schema

```
durable_knowledge
├── id (primary key)
├── title
├── content (markdown)
├── category
├── embedding (vector)
└── created_at, updated_at

short_lived_context
├── id (primary key)
├── title
├── content
├── lesson
├── embedding (vector)
├── created_at
└── expires_at

task_skills
├── id (primary key)
├── name (unique)
├── steps (markdown)
├── tags
├── embedding (vector)
└── created_at, updated_at

memory_feedback
└── Append-only outcome events, keyed by tier and memory ID

memory_metrics
└── Aggregate uses, outcome counts, success streak, and recency per memory

memory_scope
└── Optional branch/worktree fingerprint and relative file citations

fts_* tables
└── Full-text search indexes for each tier
```

### Cleanup

Expired context notes are automatically cleaned up:
- Run manually: `python -c "from database import get_db; from memory_store import MemoryStore; s = MemoryStore(get_db()); print(s.cleanup_expired_context())"`
- Auto runs on server startup

---

## Testing

Run the test suite:
```bash
python test_memory.py
```

Tests verify:
- Database initialization ✓
- OKF storage and retrieval ✓
- Context storage and retrieval ✓
- Task skill storage and retrieval ✓
- Outcome weighting, cautious anti-pattern capture, and promotion ✓
- Query weighting and citation validation ✓
- Embedding generation ✓
- Semantic similarity works ✓

---

## Performance Notes

- **First embedding generation**: ~2-3 seconds (model loads)
- **Subsequent searches**: <100ms (embeddings cached)
- **Database size**: ~50MB for 10,000 documents
- **Search throughput**: 100+ queries/second

---

## Troubleshooting

### "Memory store not initialized"
- Ensure server is running
- Check that database file can be created in `~/.copilot/`

### Embeddings slow on first run
- Normal - the ML model is loading for the first time
- Subsequent searches are fast (model stays in memory)

### Search returning irrelevant results
- Try more specific queries
- Add keywords to improve FTS matching
- Store more relevant documents to improve vector similarity

### Database locked
- Ensure only one MCP instance is running
- Database uses WAL mode for concurrent access

---

## Next Steps

1. **Store your project knowledge**: Use `store_okf()` to document your architecture and rules
2. **Use evidence-gated learning**: `learn` is available by default, but only
   call it for a reusable lesson supported by verified tests/builds, tool or
   PR results, or explicit user feedback. No signal means no memory write.
3. **Integrate with Copilot CLI**: Register the isolated local server with `copilot mcp add`
4. **Build on it**: Extend the MCP with custom tools for your specific needs

---

## Architecture Diagram

```
Copilot CLI
    ↓
MCP Server (stdio)
    ├─→ recall(query) → compact cited excerpts (full text is opt-in)
    │    ├─→ Vector Search (semantic)
    │    ├─→ FTS Search (keywords)
    │    └─→ RRF Merge + Rank
    │
    ├─→ store_okf() → Durable Knowledge
    ├─→ store_context() → Short-Lived Context
    ├─→ store_skill() → Task Skills
    ├─→ record_outcome() → Outcome Metrics
    └─→ learn() → Episodic Memory (only with reusable, verified signal)

    ↓
SQLite Database (~/.copilot/agentic_memory.db)
    ├─→ durable_knowledge + FTS index
    ├─→ short_lived_context + FTS index
    └─→ task_skills + FTS index
```

---

## Contributing & Extending

The MCP is designed to be extended. Add custom tools by:

1. Define a new tool in `server.py` using `@mcp.tool()` decorator
2. Implement backing logic in `memory_store.py` or new modules
3. Test with `test_memory.py`

Example:
```python
@mcp.tool()
def my_custom_tool(param: str) -> str:
    """Custom tool description."""
    # Your implementation
    return "result"
```

---

For questions or issues, refer to the README or check the code comments.
