# Heartbeat Execute-By-Default Design

Date: 2026-03-13
Status: Approved in chat

## Decision

Heartbeat should default to `execute` mode rather than `readonly` mode.

## Why

- AI-native unfinished-task closure requires heartbeat to be able to continue work, not merely observe it.
- The current `readonly` default blocks `write` / `edit` / `bash` in primitive runtime and prevents manager from actually resolving follow-up work such as code conflict repair and PR resubmission.
- We still want an operational safety valve, so explicit `HEARTBEAT_MODE=readonly` remains supported.

## Scope

- Change the default heartbeat mode from `readonly` to `execute`.
- Keep the environment variable override contract unchanged.
- Update prompt wording so the default message matches execute-mode semantics.
- Preserve existing readonly tests by setting the mode explicitly where needed.

## Non-Goals

- No scenario-specific execution policy logic.
- No removal of readonly support.
- No per-task mode auto-switching in this change.
