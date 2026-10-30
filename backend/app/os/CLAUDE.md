# PAI OS rules (backend/app/os)

These invariants hold for all code in this package. Each has a check.

1. Only the kernel changes task status or plan structure. *(kernel-write test)*
2. Every task has exactly one owner, a registered module. *(registry check at startup and in CI)*
3. Every outside fact cites a Knowledge row with source URL, quote, check date and status.
4. Agents propose profile changes; the student confirms them.
5. Nothing leaves on the student's behalf without an approval bound to that exact artifact version (SHA-256 of the approved source).
6. No agent holds submit, payment or credential tools.
7. **Retries:** network/service retries happen only as DBOS step retries; answer-repair happens only through Pydantic AI output validation, max 2 attempts. No other retry code. *(resolves review F5)*
8. **Side effects are idempotent.** A DBOS step can run again if the worker crashed before its result was saved, so every external effect (email, file write, any outbound call that changes something) carries an idempotency key and is recorded in `os_outbox`; a repeated send with the same key is skipped.
9. Readers (see outside content) can't act; actors never see raw outside content.
10. A running plan pins its playbook version; upgrades are explicit plan revisions (see 4.3).
11. The OS imports only its own code and ports, never old-OS or Counsellor internals. *(Tach)*
12. Nothing country-specific in code: country names, currencies, grade scales, document types and attestation bodies live in playbooks or document configs. *(red-flag search + fake routes)*
13. All dates are stored timezone-aware with their source timezone; deadlines are end-of-day in the institution's timezone unless the source says otherwise.

Done means the task's tests pass and the PR template is complete.
