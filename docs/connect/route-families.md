# Route families: playbook fields and the release flag (P3-T1)

Status: built on ADR-001 (route families, revision 2), which still awaits the owner's approval (T0). The ADR is at
`.local-ci/work/P3/adr-001-route-families-DRAFT.md` until it is approved and moved to `docs/connect/adr/`.
R-36 is not built yet: P3-T1 adds only the schema and the flag. The compiler does not resolve systems yet (P3-T4).

## New playbook fields

All of them are optional. A playbook that uses none of them loads and compiles exactly as before. The test
`tests/os/test_p3t1_family.py` checks this against a compile snapshot taken at the base commit.

| Field | Where | Meaning |
|---|---|---|
| `family: <code>` | playbook | The registry and allow-list family code this playbook serves, as lowercase letters, digits and `_`. Code maps a playbook to a family only through this field (ADR D1). |
| `fan_out: system` | step | One step per admission system, holding that system's places (D5). Allowed only in a playbook with `family`. |
| `anchor.of: system` or `system_calendar` | step anchor | The date comes from the step's admission system, or from that system's calendar, not from a route or programme fact. |
| `condition.of: system` | step condition | The fact that gates the step is read from the step's admission system. |
| `{system}`, `{body}`, `{institution}` | step title | Registry names filled in at compile time. |

### Load-time checks
A playbook with any of these mistakes fails to load:
- `fan_out: system`, `anchor.of`, `condition.of` or a title placeholder in a playbook without `family`.
- `anchor.of` or `condition.of` on a step with no system in scope. A system is in scope only when the step fans out
  per system or per programme, because a place resolves to the one system that admits it.
- A title placeholder outside its scope:
  - a step per programme may use `{system}`, `{body}` and `{institution}`;
  - a step per system may use `{system}` and `{body}`, but not `{institution}`, because a system holds several places;
  - a step that does not fan out may use none.
- An unknown title placeholder, or one that is not a plain name (for example `{system.name}` or `{0}`), or one with
  a conversion or format spec (`{system!r}`, `{body:>10}`). Titles are not formatted yet, so a doubled brace (`{{`)
  would be shown as written; until P3-T4 formats titles, keep braces out of titles.
- `anchor.of` together with `anchor.programme`, which would give one date two sources.

### The compiler, until P3-T4
A step that needs systems resolved is any step with `fan_out: system`, `anchor.of`, `condition.of` or a title
placeholder. If a playbook has such a step, `compile_plan` raises `SystemsNotResolved` and names the steps.
`SystemsNotResolved` is both a `CompileError` and a `NotImplementedError`. Such a step is never compiled without its
system, and never silently dropped. A family playbook without such steps compiles normally.

## The release flag (ADR D14)

- **Name.** The flag is `CONNECT_FAMILY_<FAMILY>`, where `<FAMILY>` is the family code in upper case. The code
  works out the name from the code (`app.os.settings.family_flag`). No family is named in code (R-58).
- **How it is read.** Through the OS settings (`OsSettings.family_flags` and `released_families`), with the same
  truthy values as the other OS flags (`1`, `true`, `yes`, `on`).
- **Default.** Off.
- **While it is off, a family playbook is not offered for new plans by:**
  - `plan_query.routes()`, the Counsellor's route list;
  - `plan_source.supports()`, and `pai_os_bridge.route_supported` through it;
  - `select_playbook`, for new Counsellor and self-serve plans;
  - the self-serve route list and the self-serve builder's `start`;
  - the self-serve programme request (`POST /programmes/requests`): the route is unknown (422) and no research is
    queued, unless the student already has an open plan pinned to that route.

  Every route without `family` stays exactly as before.
- **Plans already pinned to a family playbook keep running with the flag off.** They keep compiling, revising,
  taking Counsellor decision versions and changing programmes. They also keep their own upgrade line to a newer
  version of the same family. Readers of existing plans (packs, programme facts, the plan view) pass
  `released=None` or use `newest_plain` without `released`, so they see every playbook.
- **When it is turned on.** Not in P3. ADR-001 plans to turn on the intermediate family's flag for the P5 pilot
  (Q8).
