# Resume: local completion of pai-connect (updated 2026-11-15)

## Owner rules
- **No money.** No paid model or API calls, and no Firecrawl or Tavily. Read the web only with free WebFetch, WebSearch
  or curl.
- **Never push.**
- **Never invent data.** Every fact needs an official source, a quote and two independent checks.
- **Talk to the owner in Roman Urdu.**
- **Two people per code task:** one implementer and one independent reviewer.

**Delegation (2026-11-14):** the owner delegated all open decisions to the controller. Record each decision in LEDGER,
marked "for the owner to confirm". Do all non-paid engineering: the rest of P2, then P3 to P6.

## Environment
- **Docker Desktop.** A normal `Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'` works. When the
  owner is away, RunAs gets cancelled.
- **Restarts.** The PC and the session restart often. After a restart, restart Docker, check every worktree's
  `git status`, then resume its agent.
- **Image.** pai-ci-py.
- **Local CI.** `.local-ci/ci.sh all` takes about 2.5 hours. It archives HEAD per job, so do not move pai-connect's HEAD
  while it runs.
- **Controller DB containers.** ctl-pg and ctl-pg2 on ctl-net. The W4 DB is pai-w4-pg on pai-w4.

## Branch state
Local pai-connect head: 0d86901c.

- **P2:** T13 to T31 are merged, plus the W12 data:
  - Punjab: 794 rows.
  - BIEK: 355 rows.
  - PMDC: v2 with district regions.
  - AJK: 177 rows.
  - FDE: 82 rows.
  - The allow-lists hold 64 entries.
- **P3:** P3-T1 is merged as f8a9f5cd (family schema and the D14 flag, off by default), with the snapshot follow-up
  0d86901c.
- **Last full CI:** run on 30d70d2b. All green, except one load timeout that passed on rerun.
- **Gate 6:** the last W4 run on 0d81c0d2 measured 85.7%. Not yet re-measured with FDE, PMDC v2 and KP.

## P3
- ADR-001 draft, revision 2: `.local-ci/work/P3/adr-001-route-families-DRAFT.md`. It **awaits the owner's approval
  (T0)**. The work proceeds on its defaults.
- Next: P3-T2 (family programme binding), T3 (admission modes) and T8 (document types). Then T4 (compiler), T5, T6,
  T7, T10, T13, then T11, T12, T14, T15 and T16.

## P2 still open
- FU-17: a batch-4 alias IC-COL-001 -> IC-FDECOL-78.
- UHS lists.
- W3b, W5-W9.
- FU-2..8, 10, 13 (Counsellor lead), 14, 16.
- Spike 1 is billed, so it waits for the owner's testing.

Read LEDGER.md before starting.
