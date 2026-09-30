# Agentic Memory MCP Instructions

Use this server to retrieve narrowly relevant context and improve future work
without letting unverified outcomes or verbose memories poison retrieval.

## Efficient workflow

1. For non-trivial tasks, call `recall` once with a specific query. Use the
   compact excerpts and tier-qualified `memory_id` values; request full content
   only when an excerpt is insufficient. Check cited files against the current
   checkout. Current source, user direction, and verified results take priority.
2. Make the smallest complete change, then run the narrowest relevant check.
   Avoid repeating searches or dumping command output into memory.
3. Write or update memory only when there is a reusable lesson and an external
   ground-truth signal: passing tests/builds, compiler/test failures, verified
   tool results, PR outcomes, or explicit user confirmation/correction.
4. If there is no such signal or no reusable lesson, do not call any memory
   write tool. Do not record routine success chatter, speculation, or transcripts.

## Outcome feedback

- Call `record_outcome(memory_ids_used, outcome, signal, session_id)` only for
  memories actually used and outcomes supported by evidence. Use the exact
  tier-qualified IDs returned by recall.
- Use `success` only for a verified result, `failure` only when the memory
  plausibly contributed to the verified failure, and `user_corrected` only
  after an explicit correction. Use concise signals such as
  `unit_test_passed`, `build_failed`, `pr_merged`, or `user_corrected`.
- Do not count unrelated environment, network, or dependency failures against
  a memory. Never claim a test passed if only command execution succeeded.
- A single failure is not an anti-pattern. The server creates only a
  provisional warning after reports from three distinct session IDs; review
  causality before trusting or promoting it.
- Episodic context is promoted after three consecutive reported successes.
  Treat that threshold as useful evidence, not an automatic guarantee: only
  report externally verified outcomes and keep semantic rules concise.

## Store and retrieve carefully

- Use `learn` for a brief, evidence-backed reusable observation. Use
  `store_okf` for stable, verified project rules; use `store_skill` only for a
  repeatable workflow that is worth retaining.
- Prefer a short finding, actionable rule, verification signal, and relevant
  repository-relative citations over long background.
- Never store secrets, personal data, confidential source, raw logs,
  transcripts, or machine-specific absolute paths.
- Supply `working_directory`, `branch`, and `touched_files` to recall only
  when known and useful. These filters reduce cross-project/branch noise.
- Do not interpret RRF or utility ranking as calibrated probability.
- If memory tools are unavailable, continue without repeated retries and never
  claim recall or learning occurred.

## Implementation map

- `server.py`: MCP tool definitions and lifecycle.
- `memory_store.py`: SQLite memory storage, outcomes, promotion, retention.
- `embeddings.py`: embedding/FTS hybrid retrieval and reranking.
- `database.py`: SQLite schema and migrations.
- `config.py`: settings and local storage paths.

After Python changes run `python -m compileall -q .` and `python test_memory.py`.
Run examples only with approval to populate local data.
