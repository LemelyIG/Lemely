# I0 probes (2026-10-25)

Merge: `origin/develop` merged into `feat/tutoring-marketplace` (signed, `--no-ff`, clean; 117 commits). Pushed as `8d847b6b`.

| Probe | Result |
|---|---|
| P-1 `.venv/bin/python -c "import lemely; print(lemely.__file__)"` | `/home/sico/Code/Lemely/.claude/worktrees/tutoring-marketplace/lemely/__init__.py` (worktree) |
| P-3 `alembic heads` against `lemely_tutoring_gate` | `0043_merge_heads (head)`: T01 chains from it |
| P-4 `docker run --rm postgres:16 ls /usr/share/postgresql/16/extension/btree_gist.control` | exit 0, file present (the draft-PR CI run at I1 is the full proof) |
| P-5 `_visible_students`, `_student_detail_dto`, `teacher_student_detail` | present in `lemely/web/routers/teacher.py` |
| P-6 live DB mode | pending (I0b) |

Provisioning: `.venv` symlink to `/home/sico/Code/Lemely/.venv`; `npm --prefix web ci` exit 0.
