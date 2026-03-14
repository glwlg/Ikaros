# Task Command Design

Date: 2026-03-13
Status: Approved in chat

## Decision

Add a dedicated `/task` command for manager/task_inbox tasks, separate from `/worker`.

## First Scope

- `/task`
- `/task recent`

Both return the current user's 10 most recently updated manager tasks from `task_inbox`.

## Output

Each row should show:

- task id
- status
- source
- updated time
- compact goal summary
- optional follow-up hint such as `done_when` or `pr_url`

## Non-Goals

- No `/task <id>` detail page in this change
- No continue/retry operations in this change
- No worker-task unification in this change
