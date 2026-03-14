# Task Command Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `/task` command that lists the current user's 10 most recent manager tasks.

**Architecture:** Reuse `task_inbox` as the canonical manager-task ledger, add a lightweight command handler that reads and formats recent task snapshots, and wire it into the command router without coupling it to worker-task views.

**Tech Stack:** Python 3.14, asyncio, Telegram/UnifiedContext command handlers, file-backed task inbox, pytest/pytest-asyncio

---

### Task 1: Add command-handler tests for `/task`

**Files:**
- Create: `tests/handlers/test_task_handlers.py`
- Modify: `src/handlers/start_handlers.py`

- [ ] **Step 1: Write failing tests for `/task` and `/task recent`**
- [ ] **Step 2: Run `uv run pytest tests/handlers/test_task_handlers.py -q` and watch it fail**

### Task 2: Implement the `/task` handler

**Files:**
- Create: `src/handlers/task_handlers.py`
- Modify: `src/handlers/__init__.py`
- Modify: `src/handlers/start_handlers.py`

- [ ] **Step 1: Parse `/task` subcommands with a minimal `recent` default**
- [ ] **Step 2: Read the current user's recent `task_inbox` snapshots**
- [ ] **Step 3: Format the 10 most recent rows with follow-up hints**
- [ ] **Step 4: Keep `/worker` behavior unchanged**

### Task 3: Verify routing and runtime behavior

**Files:**
- Test: `tests/handlers/test_task_handlers.py`
- Test: `tests/core/test_ai_handlers_dispatch.py`

- [ ] **Step 1: Run `uv run pytest tests/handlers/test_task_handlers.py tests/core/test_ai_handlers_dispatch.py -q`**
- [ ] **Step 2: Rebuild `x-bot` so the new command is available in container runtime**
