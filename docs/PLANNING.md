# Life Dashboard — Planning

## Vision

A single personal command centre that replaces scattered to-do apps, calendar screenshots, and sticky notes.  It runs locally (no cloud dependency), looks good, and is fast to update day-to-day.

---

## Goals

### Short-term (now → 1 month)
- [x] Working Flask + TinyDB application with full CRUD
- [x] Three core views: This Week, Tasks, Projects & Year Ahead
- [x] Edit/add/delete modals for all data types
- [ ] Personalise sample data with real tasks, events, projects
- [ ] Set recurring weekly review time (Sunday evening)

### Medium-term (1–3 months)
- [ ] Add a **Notes** tab for free-form weekly journals / brain dumps
- [ ] Week-over-week task carry-forward (unfinished tasks auto-suggest roll to next week)
- [ ] Simple search / filter bar across all items
- [ ] Keyboard shortcuts (n = new task, e = edit selected, Esc = close modal)
- [ ] Export a weekly summary as a PDF or plain text

### Longer-term (3–12 months)
- [ ] Optional calendar sync (read-only iCal import so external meetings appear)
- [ ] Basic analytics view: tasks completed per week over time
- [ ] Mobile-friendly layout improvements
- [ ] Dark mode toggle

---

## Decisions Log

| Date       | Decision                                      | Rationale                                                    |
|------------|-----------------------------------------------|--------------------------------------------------------------|
| 2026-02-28 | Use TinyDB over SQLite                        | Schema-free, human-readable JSON, zero config                |
| 2026-02-28 | Single-page app with fetch() rather than Jinja2 forms | Snappier UX, no page reloads, cleaner CRUD modal pattern |
| 2026-02-28 | Remove Health & Finance tabs initially        | Keep scope tight; add back when core is solid                |
| 2026-02-28 | No user authentication                        | Local-only tool; add if ever deployed to a shared host       |

---

## Weekly Review Checklist

Run this every Sunday (15 min):

1. Mark completed tasks as done
2. Move unfinished high-priority tasks to new due dates
3. Add events for the coming week
4. Update project progress percentages
5. Add one new milestone to the Year Ahead if anything has changed
6. Glance at the KPI bar — are the numbers moving in the right direction?

---

## Backlog

Items not yet prioritised:

- Recurring tasks (e.g. "team standup" every Mon/Wed/Fri)
- Sub-tasks / checklists within a project
- Tagging / multi-category items
- Bulk import from CSV
- Drag-and-drop reordering of tasks
- Notifications / reminders (OS-level via cron + notify-send)
