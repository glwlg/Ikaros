# Heartbeat Execute-By-Default Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make heartbeat run in execute mode by default while preserving explicit readonly override support.

**Architecture:** Change the default mode source in `HeartbeatWorker` from `readonly` to `execute`, then cover the new contract with focused heartbeat tests. Leave the runtime policy switch and readonly-mode code path intact so environments can still force readonly with `HEARTBEAT_MODE=readonly`.

**Tech Stack:** Python 3.14, asyncio, heartbeat runtime, pytest/pytest-asyncio

---

### Task 1: Lock the new default in tests

**Files:**
- Modify: `tests/core/test_heartbeat_worker.py`

- [ ] **Step 1: Write a failing test for execute-by-default heartbeat mode**
- [ ] **Step 2: Run `uv run pytest tests/core/test_heartbeat_worker.py::test_heartbeat_worker_defaults_to_execute_mode -q` and watch it fail**
- [ ] **Step 3: Keep explicit readonly-mode coverage intact**

### Task 2: Switch the default mode

**Files:**
- Modify: `src/core/heartbeat_worker.py`

- [ ] **Step 1: Change the fallback `HEARTBEAT_MODE` value from `readonly` to `execute`**
- [ ] **Step 2: Update execute-mode prompt text if needed so the default wording stays accurate**
- [ ] **Step 3: Run heartbeat-focused tests and verify they pass**

### Task 3: Verify runtime behavior

**Files:**
- Test: `tests/core/test_heartbeat_worker.py`
- Test: `tests/core/test_prompt_composer.py`

- [ ] **Step 1: Run `uv run pytest tests/core/test_heartbeat_worker.py tests/core/test_prompt_composer.py tests/core/test_ai_handlers_dispatch.py -q`**
- [ ] **Step 2: Rebuild `x-bot` so container runtime picks up the new default**
