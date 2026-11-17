# Handoff: branch `paios-and-paic` (PAI Counsellor + PAI OS in one app)

- **Date:** 2026-11-17.
- **Written for:** the next developer, who takes over this work.
- **Status:** local only. This branch has never been pushed.

## 1. What this branch is

`paios-and-paic` is `origin/pai-merge` with a `--no-ff` merge commit of the local `pai-connect` branch on top. Its
merge commit is `7368a8ac`, and the merged head of `pai-connect` was `0d86901c`.
- It holds the connection work between the PAI Counsellor (PAI C) and PAI OS: phases P0, P1 and P2, plus the first
  P3 task.
- **Everything in this branch was built by one implementer and checked by one independent reviewer per task.** The
  data was checked twice, independently. Nothing unreviewed is in this branch.
- The owner asked for this branch on 2026-11-17. It goes ahead of the plan's rule, from the root CLAUDE.md and P0-D14,
  that nothing merges into `pai-merge` until the whole plan is complete. This branch is separate from `pai-merge`; it
  does not change it.

**Read first:**
1. The root `CLAUDE.md` and `backend/app/os/CLAUDE.md`. Their rules are not optional.
2. The master spec, `docs/superpowers/specs/2026-11-03-pai-connect-design.md`, §2-§3 and §12.
3. `docs/connect/handoff/p2-handoff.md`. This is the P2 state, with the local evidence, controller decisions and open
   gaps.
4. This file.
5. `docs/connect/handoff/local-run/LEDGER.md`: every task, review, ruling and finding of the local run, in order.

## 2. Rules the owner set for this run

These still apply. Check with the owner before changing any of them.
- **No money.** No paid model or API calls, and no paid crawling tools. The billed checks (Spike 1, Spike 2, live
  graded Counsellor runs) wait for the owner's testing phase.
- **Never invent data.** Every institution, date, fee, merit figure or rule needs an official source, a verbatim quote
  and **two independent checks**. For allow-lists and list data, two independent AI checks are enough (owner ruling,
  2026-11-14).
- **Every code task gets an implementer and an independent reviewer.** Run fix rounds until the reviewer approves,
  then squash-merge.
- **No country names in `backend/app/os` code (R-58).** Anything country-specific lives in data.
- **Never edit `.env`.** Never print secrets. DB changes go through Alembic only.
- **Do not touch the frozen Counsellor files** (master §10). Counsellor files under CODEOWNERS need the Counsellor
  lead's review.
- **Decisions:** the owner delegated the open decisions to the local controller. Every one of them is marked "for the
  owner to confirm at sign-off" in `p2-handoff.md` §3 and in the LEDGER, and still needs his confirmation.

## 3. State by phase

| Phase | State |
|---|---|
| P0 Setup, Counsellor fixes | Done, signed off. |
| P1 Connection core | Done, signed off. |
| P2 National data system | Mostly built and checked locally. Not signed off. Details below. |
| P3 Intermediate family | ADR-001 drafted and reviewed; it needs the owner's approval. P3-T1 is built. T2, T3, T6, T7 and T8 exist as WIP branches (§5). |
| P4 Bachelor's family | Designed only: `docs/connect/design/p4-p6-core-design-DRAFT.md`. |
| P5 Launch (code part) | Designed only. P5-T2 was started but has no commits. |
| P6 Abroad | Designed only. |

### P2: what is built (tasks T13-T31, all reviewed)

| Area | What |
|---|---|
| Import | Import aliases (T13); a workbook from re-entered values (T14); official-list union (T16); a programme under a non-institution becomes a rejected row (T18) |
| Allow-list | A per-row allow-list family (T19, T21); 64 reviewed allow-list entries, each with two checks (T20, D-ALLOW, D-ALLOW-KP); a race-safe allow-list sync (T20) |
| Page cache | A page from the cache is never served to a scope it is not listed for (T22) |
| Programmes | R-15 OS side: an excluded field leaves the OS lists, and a planned place becomes a proposal (T24). `built: true` depends on FU-13 |
| Playbooks | Germany master v3 asks for the transcript and CGPA (T25); a board may be the parent of a calendar (T26) |
| Registry | List progress ignores withdrawn rows (T27); an aliased list row adds that list to the existing entity (T28) |
| Tools | A list-workbook builder that needs two independent extractions (T29); the dry run plans like the import (T31) |

**P2 registry data (W12).** Each row comes from two independent extractions and an independent review:

| Source | Rows |
|---|---|
| HED Punjab public colleges | 794 |
| BIEK Karachi colleges | 355 |
| PMDC medical/dental colleges | 179 (74 placed by the PBS census district table) |
| HED AJK colleges | 177 |
| FDE ICT colleges | 82 |

The workbooks, the extractions and a README for each are under `docs/research/batches/w12/`.

**Gate 6 (registry coverage):** measured locally at 85.7% (2088/2435), on an earlier head. Measure it again with the
W4 local import, which now includes FDE, PMDC v2 and KP. The steps are in the LEDGER (W4 lines).

**Last full local CI.** It ran on commit `30d70d2b`, and everything passed:

| Suite | Result |
|---|---|
| os | 3123 passed. One crash test timed out under load, and passed when re-run alone. |
| standalone | 51 passed |
| legacy | 4004 passed |
| frontend | 602/602 |
| alembic heads, traceability | OK |

The later merges (T25, the data, P3-T1) were checked with targeted test runs. **Run the full CI again on this
branch.**

## 4. P3, P4, P5 and P6 designs (not approved yet)

- `docs/connect/design/adr-001-route-families-DRAFT.md`: ADR-001 for route families (R-81).
  - Option C: one generic family playbook, compiled per place from the registry.
  - Decisions D1-D14 and tasks T0-T16.
  - Nine owner questions, each with a default.
  - `adr-001-review.md` is its independent review. Revision 2 applies it.
- `docs/connect/design/p4-p6-core-design-DRAFT.md`: the core engineering for P4, P5 and P6. Read its §0 first. It found
  that:
  - launch-gate reading (b) passes while checking nothing;
  - `national` is used as a global constant;
  - the release flag is global;
  - MeritCheck ignores formulas owned by a system.
- `docs/connect/route-families.md`: what P3-T1 built. These are the family fields and the D14 release flag,
  `CONNECT_FAMILY_<FAMILY>`, which is off by default.

## 5. Work in progress: NOT in this branch, not reviewed

These local branches exist only in the owner's repo. Hand them over separately, for example with `git bundle`, or
start the tasks again from their briefs. Each one needs an independent review before it is merged.

| Branch | Task | Commits on 0d86901c |
|---|---|---|
| `pc/p3-t2-family-binding` | ADR D4: programmes bound by family; the importer writes family; backfill | 7 |
| `pc/p3-t3-admission-modes` | ADR D3: admission-mode vocabulary; mode-gated steps stay provisional until verified | 5 |
| `pc/p3-t6-region-intakes` | ADR D9: region-aware intakes | 4 |
| `pc/p3-t7-events` | ADR D12: the six R-39 events | 5 |
| `pc/p3-t8-document-types` | ADR D13: document types, Spike 2 fixtures | 4 |
| `pc/p5-t2-first-live-route-facts` | P5-D2 and P6-D4: an honest gate (b) and route facts in the gate | 0 (not started) |

The task briefs, which hold the exact scope and rules, are in the owner's `.local-ci/work/briefs/`
(`P3-T2-brief.md` and so on). The LEDGER refers to them.

## 6. Next steps, in order

1. **Owner:** approve ADR-001 (P3-T0), or change it, and answer its questions Q1-Q9.
2. **Review and merge** the WIP branches in §5, then run the full CI.
3. **P3 critical path:** T4 (the compiler resolves place → system), then T5, T10, T13, T11 + T12 (data), T14 (Stage H,
   with the Counsellor lead), T15 and T16 (the gate).
4. **P4, P5 and P6:** follow the design's task tables. These can start once P3-T2 and P3-T3 are merged: P5-T1, P5-T3,
   P5-T5, P6-T1, P6-T3 and P4-T2.
5. **P2 follow-ups:** take these from the LEDGER. Each is its own small task.
   - FU-2/FU-14: list evidence for a list taken from the entity's own row.
   - FU-4, FU-5, FU-16: dry-run edge cases.
   - FU-6, FU-7, FU-8.
   - FU-10: the page cache for renders.
   - FU-13: `pai_c/connect/places.py` passes the student. This needs the Counsellor lead, and must land before P2 sign-off,
     or R-15 goes back to unbuilt.
   - FU-17: a batch-4 alias IC-COL-001 → IC-FDECOL-78.
   - The UHS lists. W3b and W5-W9 (see the LEDGER work list).
6. **Data that stays open:**
   - 14 PMDC rows without a region.
   - Unproven hosts: `hed.ajk.gov.pk`, which is compromised with spam, `jac.ajk.gov.pk`, `imcgf72.edu.pk` and
     `gcwg.punjab.gov.pk`.
   - A-level and private-college lists.
   - Balochistan and GB admission data.

## 7. Running it locally

- **Tests.** Run in Docker. Example: `docker run --rm --network <net> -e OS_TEST_DATABASE_URL=postgresql://os_test:os_test@<pg>:5432/os_test -v "<repo>":/repo -w /repo/backend <python image> python -m pytest tests/os -q`.
  Then run `tach check`, `python scripts/check_traceability.py --gate P2` and `python scripts/check_freeze.py`.
- **The full app** (`python scripts/run.py`) needs a `.env`. This branch has none, and none was created in this run.
  - A copy of `.env.example` with no keys starts the stack with PAI OS offline and in rehearsal mode (the compose
    defaults), at no cost.
  - Real keys make Counsellor chat calls, which are paid. Agree that with the owner first.
- **On Windows**, start Docker Desktop. Sessions and the PC restarted often during this run, so make WIP commits
  after every small step.

## 8. Owner decisions still open (short list)

- **ADR-001 approval and Q1-Q9.** The P4-P6 design questions.
- **The controller decisions in `p2-handoff.md` §3:**
  - the allow-list body family rule;
  - the derived quotes and identical-extraction rulings for the W12 data;
  - the PMDC address-only region rule and the PBS district rule;
  - leaving out hed.ajk.gov.pk;
  - the R-15 conditions;
  - Germany v3's three student sentences;
  - the board → calendar parent.
- **`coverage/launch.yaml` first-live values** (D-17) for the launch gate.
- **Billed runs:** Spike 1 and Spike 2, and their cost cap.
