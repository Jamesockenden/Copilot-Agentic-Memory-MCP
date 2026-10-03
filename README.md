# Agentic Memory MCP Server for Copilot CLI

An MCP server that provides persistent, searchable memory for Copilot CLI sessions using hybrid retrieval (vector search + FTS5 + RRF).

## Architecture

### Three Memory Tiers
1. **Durable Knowledge**: Long-term facts (Markdown OKF format)
2. **Short-Lived Context**: Episodic notes, fixes, lessons learned
3. **Task Skills**: Reusable workflows and procedures

### Hybrid Retrieval Pipeline
- **Vector Search**: cosine similarity over stored sentence-transformer embeddings
- **Full-Text Search**: FTS5 for exact keywords and symbols
- **Intent-aware RRF**: Exact paths, symbols, and error identifiers favor FTS5; conceptual queries favor vector search
- **Outcome-aware ranking**: Verified uses adjust a per-memory Bayesian success estimate with temporal decay
- **Scope and citation guards**: Optional branch/worktree/touched-file filters and on-demand file/line validation

### Outcome Feedback and Promotion

On startup and shutdown, transient context is evicted after 14 days, eligible
lessons are promoted to OKF Markdown, and SQLite performs incremental vacuuming.
Shutdown retries a WAL checkpoint with truncation when another connection is
temporarily active. Context retrieval tracks access counts and timestamps;
frequently accessed or explicitly fixed lessons are promoted. Three consecutive
successful outcomes also promote an episodic lesson to durable OKF. A vector
similarity check appends insights to an existing durable document when
similarity is at least 85%, avoiding duplicate OKF files.

Outcome counts and events live in relational SQLite tables separate from
embeddings. One failure only lowers the smoothed success estimate; it never
deletes or permanently suppresses a memory. A provisional anti-pattern note
is created only after failures are reported from three distinct sessions, and
requires review before being promoted. Memory scope stores only a hash of the
working-directory path; source references remain repository-relative.

Short-lived search results use a 0.5 tier weight and exponential age decay,
and are restricted to the most recent 48 hours. Durable knowledge uses a 1.0
tier weight. Candidate ranking additionally uses
`(successes + 1) / (total_uses + 2)` with age decay, then applies its sigmoid
factor to the weighted RRF score.

## Setup

On Windows, the setup script creates an isolated virtual environment, installs
dependencies, and downloads/tests the embedding model once:

```powershell
.\setup-local.ps1
```

Then run the `copilot mcp add ...` command printed by the script. The model is
cached in Hugging Face's shared user cache; configure `HF_HOME` or
`HF_HUB_CACHE` before setup if you want to relocate it. See [SETUP.md](SETUP.md)
for Windows/macOS/Linux setup and optional offline mode.

Manual environment install:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The MCP SDK is constrained to version 1.x because current Copilot CLI clients
request protocol `2025-11-25`, which MCP SDK 2.x does not negotiate.

## Running the Server

```powershell
.\.venv\Scripts\python.exe __main__.py
```

## Tools Available

- `recall(query, limit, working_directory, branch, touched_files, include_full_content)`: Retrieve compact excerpts by default; results include tier-qualified `memory_id` citations. Full content is optional and capped.
- `record_outcome(memory_ids_used, outcome, signal, session_id)`: Report success, failure, or user correction for cited memories
- `store_okf(title, content, category, working_directory, branch)`: Store durable knowledge
- `store_context(title, content, lesson, ttl_days, memory_kind, working_directory, branch)`: Store short-lived context or an explicit anti-pattern
- `store_skill(name, steps, tags, working_directory, branch)`: Store task skills
- `learn(observation, category)`: Log learning from session
- `mark_lesson_fixed(context_id)`: Promote a confirmed lesson to durable knowledge

The `learn` tool is available by default, but availability is not an instruction
to write on every task. Call it only when there is both a reusable lesson and an
external ground-truth signal (verified tests/builds, tool results, PR outcomes,
or explicit user feedback). Report outcomes only for memories actually used
and only when evidence supports the outcome and causal link. No signal or no
reusable lesson means no memory write. Supply a stable session identifier only
when known; never fabricate one. Lessons use the configured
`AUTO_LEARNING_TTL_DAYS` retention period. Do not store secrets, raw logs,
transcripts, or ephemeral personal details.

## Memory Format

### Durable Knowledge (OKF)
```markdown
# Architecture: User Authentication

## Overview
JWT-based authentication system...

## Rules
- Tokens expire after 24 hours
- Refresh tokens valid for 30 days
```

### Task Skills
```markdown
# Deploy to Production

## Steps
1. Run tests: `npm test`
2. Build: `npm run build`
3. Deploy: `npm run deploy`
```
