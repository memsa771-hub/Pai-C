# Student Vault spec (24 Oct 2026)

Founder-approved design for the student Vault: the student's digital twin. Visual plan:
https://claude.ai/artifact/4szPK86jiYEo5ebW8UWSse

## Goal
Everything known about a student lives in one Vault, arrives through one pipeline, carries evidence,
is stored in English, and can be seen, confirmed, edited and removed by the student. New kinds of
information are added through the catalog, not new code. The analyzer (mirror, relations, paths,
opportunities, roadmaps) is derived from the Vault and is out of scope here.

## Inputs (all through one door: normalize → candidate → validate → reconcile → Vault)
1. Chat (text, voice transcript): one extraction call per student turn.
2. Documents: stay in the Documents view (PDF, DOCX, and JPG/PNG photos read by OCR). Vault entries keep
   the file id and page; the UI shows a document icon that opens that file.
3. Details page: forms and dropdowns for structured facts.
4. Story cards: typed text and chips for story items.

## Storage
- Structured, heavily queried types keep their typed storage: Vault facts (field definitions) and
  typed records (education, course, test_attempt, goal, activity, project, achievement, skill, ...).
- Every other type is a catalog item in one generic item store, validated by the catalog's JSON schema
  and versioned (`type_version`). Items: interest, strength, value, pressure, option, myth, certainty,
  family_member, domicile, quota, daily_life.
- Catalog file (`app/memory/catalog/vault_catalog.json`) defines every type: storage, shown_on
  (details | story), inputs, sensitivity, conflict rule, freshness days, schema, and the choice lists
  (levels, intermediate groups, boards, tests, provinces, quotas, relations, budget bands).

## Language
- Values are stored and shown in English only. The UI never shows the student's original words.
- The original words are kept internally as the verbatim evidence quote (anti-fabrication check,
  translation audit, conflict decisions) with `source_language` (en | ur | roman_ur | mixed).
- Names in Latin script; a name still in Urdu script is kept as a guess that needs confirmation.
- Digits normalized to ASCII, dates ISO (Pakistani day/month order), money in PKR, catalog codes for
  choice fields. A value that is still not English (Urdu script outside names) is rejected and logged.
- Every entry shows an English badge: Stated, From document, PAI's guess, Confirmed, In question.

## Evidence ladder
inferred (PAI's guess) < stated (student said or typed) < shown (document) < confirmed (student approved).
A guess never replaces a stated item. A student's own edit always wins; a disagreeing document stays
visible on the entry.

## Conflicts (decided in this order for every type)
1. Same meaning → merge (one entry, more evidence).
2. Student's own edit → student wins, old value in history, disagreeing document kept visible.
3. Explicit correction or change over time (student's quote says so) → replace, history kept.
4. New value is only a guess against a stated entry → keep the stated entry, log the guess.
5. Catalog rule: latest_wins (change-prone), evidence_wins (objective: document beats chat, student told),
   ask_student (stable: conflict card).
Also: family members resolved by relation; another person's document (name mismatch) is not applied and
raises a question; OCR-read values are not "shown" until confirmed; a removed entry returns only when the
student states it again; one write at a time per student. Not conflicts: someone else's wish (owner kept),
tension in the story, scale or format differences (raw value and scale kept).
Conflict cards: one question at a time, four answers (keep current, use new, both true at different times,
neither: student writes it); unresolved entries are "In question" and never block the rest of the Vault.

## Money
Never ask household income. Ask an approximate yearly study budget as a range: under 1 lakh, 1–3 lakh,
3–6 lakh, 6–10 lakh, over 10 lakh, not sure yet; what it covers (fees only, fees + hostel); whether study
is possible without a scholarship. "Can't afford" in chat becomes a stated pressure, never a number.

## Freshness
Each type has a freshness window (marks never, budget 180 days, goals 90, family 365). Past it the entry
is flagged for re-confirmation.

## Access
Student: everything. Counselor: relevant entries, sensitive only when needed, restricted never.
PAI OS: the handoff summary only.

## Measures
Golden set recall ≥ 95% on core facts; zero silent drops (every drop logged with its reason); 100% of
values in English with the original quote kept; one place for everything; a new item type works from a
catalog entry alone; document entries open the right file and page; every conflict type has a test.
