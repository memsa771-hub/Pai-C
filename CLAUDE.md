# Working rules

- Never paste API keys or real student data into Claude.
- One component per PR.
- Task branches start from and rebase on `pai-os`. `pai-os` merges into `dev` only at slice gates.
- OS code lives only in `backend/app/os`.
- Shared files need a reviewer from each team.
- Run `tach check` and `pytest tests/os` before pushing.
