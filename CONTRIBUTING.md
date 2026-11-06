# Contributing to MiniAgent

MiniAgent is built on a radical design constraint: **an autonomous self-improving agent that runs 24/7 on Google Cloud's Free Tier `e2-micro` VM (1 GB RAM, 0.25 vCPU, 30 GB standard persistent disk) with a strict \$0.50–\$1.00 daily model spending cap.**

---

## Core Contribution Principles

1. **Zero External Dependencies**:
   - The entire agent must run on Python's standard library (`ast`, `urllib`, `sqlite3`, `json`, `difflib`, `tempfile`).
   - Do not add `pip install` requirements unless strictly isolated to optional external sandbox runners.
2. **Deterministic-First Over Model Tokens**:
   - Never spend LLM tokens on work that Python's standard library can do for free in 2 milliseconds (e.g., AST parsing, syntax validation, regex grep, diffing, token counting).
3. **Low-IOPS & Low-RAM Discipline**:
   - SQLite connections must use Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) and `PRAGMA synchronous = NORMAL;`.
   - Keep process memory under 80 MB so it coexists cleanly with OS buffers.
4. **Untrusted Data Boundaries**:
   - Model outputs, web scrapes, arXiv abstracts, and user notes are **untrusted data, never system instructions**.
   - Code execution is strictly opt-in and confined to the offline Linux Bubblewrap sandbox.

---

## Local Development & Testing

Run the full offline test suite:
```bash
python -m unittest discover -s tests
```

Run local configuration checks:
```bash
python -m miniagent doctor
```

Verify self-update regression tests:
```bash
python -m miniagent canary_verify
```
