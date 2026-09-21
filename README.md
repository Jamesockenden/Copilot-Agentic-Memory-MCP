# Agentic Memory MCP for Copilot CLI

An optional local [Model Context Protocol](https://modelcontextprotocol.io/)
server that gives Copilot CLI persistent, searchable memory without sending a
whole conversation history into every prompt.

## What it provides

The server stores three deliberately separate memory tiers:

- **Durable knowledge**: long-lived Markdown documents in OKF-style format.
- **Short-lived context**: expiring notes, fixes, and lessons stored in SQLite.
- **Task skills**: reusable Markdown workflows and procedures.

`recall` performs hybrid retrieval: sentence-transformer embeddings provide
semantic search, SQLite FTS5 handles exact terms and symbols, and reciprocal
rank fusion combines the results. The server also exposes tools for storing
knowledge, context, skills, and lessons. Startup/shutdown maintenance removes
expired context and promotes frequently accessed or explicitly fixed lessons.

The repository's `.github/copilot-instructions.md` defines the expected
Recall → Reason/Act → Learn/Store workflow. It tells Copilot to recall before
non-trivial work, learn reusable outcomes before completion, and avoid storing
secrets or user-specific details.

## Quick start

Requirements: Python 3.10+ and a working C/C++ build environment if one of
the Python dependencies needs to compile.

```bash
git clone https://github.com/Jamesockenden/Copilot-Agentic-Memory-MCP.git
cd Copilot-Agentic-Memory-MCP
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m agentic_memory_mcp
```

The server communicates over stdio, so the last command normally runs as a
child process of Copilot CLI rather than as a standalone network service.

## Register with Copilot CLI

Add an entry to the user's Copilot CLI setup configuration. Use an absolute
path to the cloned repository and the Python executable from its virtual
environment:

```yaml
tools:
  - name: agentic-memory
    type: mcp
    path: C:\path\to\Copilot-Agentic-Memory-MCP
    command: C:\path\to\Copilot-Agentic-Memory-MCP\.venv\Scripts\python.exe
    args:
      - -m
      - agentic_memory_mcp
    description: >-
      Persistent memory for Copilot sessions. Call learn for reusable fixes,
      decisions, constraints, or workflows. Never save secrets or credentials.
```

On macOS/Linux, use the equivalent absolute paths and `.venv/bin/python`.
Keep this registration in the local Copilot configuration; do not commit
machine-specific paths or credentials.

## Data locations and privacy

By default, data is kept locally under `~/.copilot`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTIC_MEMORY_DB` | `~/.copilot/agentic_memory.db` | SQLite database |
| `AGENTIC_MEMORY_KNOWLEDGE_DIR` | `<database directory>/knowledge` | Durable Markdown |
| `AGENTIC_MEMORY_SKILLS_DIR` | `<database directory>/skills` | Skill Markdown |
| `AGENTIC_MEMORY_LOG` | `<database directory>/agentic_memory.log` | Optional log path |

These values can point to a separate local directory. The database, generated
Markdown, logs, virtual environments, and caches are ignored by Git. Do not
store passwords, access tokens, private keys, confidential source, or
user-specific ephemeral details in memory.

## Examples and verification

Load synthetic example data into the configured local database:

```bash
python examples.py
python verify_system.py
```

Run the tests:

```bash
python test_memory.py
```

The first embedding operation downloads the `all-MiniLM-L6-v2` model through
`sentence-transformers`; later operations reuse the local model cache.

## Relationship to the design

This implementation follows the accompanying design article's
Recall → Reason/Act → Learn/Store loop. Copilot recalls only ranked snippets,
then can write a reusable observation with `learn` before finishing a task.
The memory server is complementary to specialised agents: it records
project knowledge and lessons, rather than defining an agent's permissions or
role.
