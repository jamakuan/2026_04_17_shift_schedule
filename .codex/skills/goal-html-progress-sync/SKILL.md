---
name: goal-html-progress-sync
description: Update the repo's `goal.html` progress page when plans or tasks change; use when adding a new top plan card, reordering plans, syncing completion status/timestamps, or keeping the progress page aligned with the latest implementation work.
---

# Goal Html Progress Sync

## When To Use

- `goal.html` needs a new plan card or a newer plan must move to the top.
- A task changes state and the page must reflect the new status, completion time, or summary.
- The user asks whether `goal.html` still matches the current plan progress.
- The user wants the progress page to stay in sync with completed implementation work.

## Workflow

1. Open the current `goal.html` and identify the existing plan cards.
2. Add the newest plan card above older plans.
3. Keep each plan card self-contained with its own task table.
4. When a task is finished, update `goal.html` immediately before moving on to the next task.
5. Mark only completed tasks as `已完成` and give them a completion time.
6. Use `—` for `進行中` and `待處理` completion times.
7. Keep the existing HTML style and structure unless the user explicitly asks for a redesign.
8. Update the page's `最後更新` timestamp when the visible content changes.

## Update Rules

- Treat the newest plan as the first card in the list.
- Preserve older plan cards below the newest one.
- Keep task rows factual and short.
- When the user says a phase is finished, move that task to `已完成` and fill in the real completion time.
- Do not invent completion times for unfinished tasks.
- Do not wait for a separate reminder to write the progress entry; if the task is done, write the entry right away.
