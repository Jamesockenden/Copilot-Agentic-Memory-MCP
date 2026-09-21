# Setup guide

This guide describes a clean, per-user installation. It intentionally does
not include any existing database, logs, account details, or local paths.

## 1. Install

```bash
git clone https://github.com/Jamesockenden/Copilot-Agentic-Memory-MCP.git
cd Copilot-Agentic-Memory-MCP
python -m venv .venv
```

Activate the environment, then install dependencies:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# macOS/Linux
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 2. Configure Copilot CLI

Add the `agentic-memory` MCP tool to the user's Copilot CLI setup file. The
file is commonly `~/.copilot/copilot-setup-steps.yml`; its exact location can
vary by CLI installation. Replace both placeholder paths with absolute paths
on the local machine:

```yaml
tools:
  - name: agentic-memory
    type: mcp
    path: /absolute/path/to/Copilot-Agentic-Memory-MCP
    command: /absolute/path/to/Copilot-Agentic-Memory-MCP/.venv/bin/python
    args: ["-m", "agentic_memory_mcp"]
    description: >-
      Persistent memory for Copilot sessions. Call learn for reusable fixes,
      decisions, constraints, or workflows. Never save secrets or credentials.
```

For Windows, use the repository directory and
`.venv\Scripts\python.exe`. Do not commit this user-specific registration.

The repository also includes `.github/copilot-instructions.md`. Keep that file
in the checkout: it provides the agent-facing rules to recall before work,
act using current source and tests, learn reusable outcomes, and reject
sensitive or user-specific memory. If the MCP is installed in a separate
local checkout, copy the file's contents to that checkout as well.

## 3. Optional local smoke test

The MCP process uses stdio and waits for protocol input, so it is normally
started by Copilot CLI. To initialize synthetic data and check retrieval:

```bash
python examples.py
python verify_system.py
```

Run `python -m agentic_memory_mcp` only when testing the MCP process directly.
Stop it with Ctrl+C.

## 4. Configure storage (optional)

Set these environment variables before starting Copilot if the default
`~/.copilot` location is not suitable:

```text
AGENTIC_MEMORY_DB=/local/private/path/agentic_memory.db
AGENTIC_MEMORY_KNOWLEDGE_DIR=/local/private/path/knowledge
AGENTIC_MEMORY_SKILLS_DIR=/local/private/path/skills
AGENTIC_MEMORY_LOG=/local/private/path/agentic_memory.log
```

Use a private directory and back it up according to its sensitivity. Memory
is local by design; this project does not upload the database to GitHub.

## Memory lifecycle

- Durable knowledge and skills remain until updated or deleted.
- Short-lived context defaults to 30 days and is restricted to the latest
  48 hours during retrieval.
- Maintenance removes expired/retained context on startup and shutdown.
- A context note read at least three times, or marked fixed, can be promoted
  to durable knowledge.

## Available MCP tools

`recall`, `store_okf`, `store_context`, `store_skill`, `learn`,
`mark_lesson_fixed`, `list_knowledge`, `list_skills`, and
`list_recent_context`.

Only store information that is safe for the local user and project. In
particular, never store credentials, secrets, private keys, or confidential
content.
