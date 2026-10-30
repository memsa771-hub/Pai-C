# Runbook: a programme's semester start (`semester_start`)

The visa step's date is derived from the visa programme's `semester_start`: 6 weeks before the first day of
lectures (playbook `germany_master` v1, `visa_apply` anchor). Research looks for it on the programme's pages and on
the university's academic calendar. When research cannot confirm it, an admin supplies it. This runbook covers both.

## What the student sees meanwhile

- Until a programme has a `semester_start`, the visa step is listed in the inbox as **blocked** with the line
  **"Waiting for your programme's semester start date"**. Nothing can be tapped on it. Every other step is unaffected.
- When a date is stored (by research or by an admin), the plan is revised. The visa step gets its due date and the
  note "Apply by {due}: 6 weeks before your semester starts on {date}. ...", which cites the source page.
- A date stored as `unconfirmed` is still used, but the step is marked provisional and the check stays open.
- Before the student is admitted anywhere, the date follows the earliest semester start of their programmes.

## Where research looks

Each programme's `start_urls` (`backend/app/os/knowledge/seed/programmes_germany.yaml`) include the university's
academic calendar. The research profile (`germany_master.research.v1.yaml`) marks `semester_start` as
`university_wide`. A page on the programme's own university domain whose title is in `university_wide_titles` (for
example "Academic Calendar") counts as in scope for that field only, though it names no programme.

| University | Calendar page | What it said on 2026-10-30 |
|---|---|---|
| OVGU Magdeburg | https://www.ovgu.de/unimagdeburg/en/academiccalendar-p-49226.html | WS 2026/27 and WS 2027/28. WS 2027/28 classes (all faculties except medicine): October 11, 2027 - January 28, 2028 |
| TU Chemnitz | https://www.tu-chemnitz.de/studierendenservice/termine.php.en | WS 2026/27 only: begin of lectures 12.10.2026. WS 2027/28 is not published yet |
| BTU Cottbus-Senftenberg | https://www-docs.b-tu.de/studierende/public/termine-fristen/Termine_WiSe_2027_28.pdf | WS 2027/28: lecture period 04.10.2027 - 30.01.2028 |

The BTU link names one winter semester. For the 2028 intake, change it to `Termine_WiSe_2028_29.pdf`. The list is at
https://www.b-tu.de/studium/im-studium/studienorganisation/quicklinks/termine-fristen. OVGU's official notice for
2027/28 is "Studienjahresablaufplan 2027/2028" (Amtliche Bekanntmachung Nr. 62/2025): Lehrveranstaltungszeit from
11 October 2027.

Every reader is told the target intake (the profile's `target_cycle`, e.g. "WS 2027/28"), so on a calendar that
lists several semesters it gives that intake's date. A date for an older winter semester is never confirmed for a later intake: the fact stays `unconfirmed` with the
reason `cycle_old:<year>` and the note "page shows ...". Research runs again each day while the check is open, so it
confirms the date by itself once the page has the new semester.

## Commands

The script runs the same code as the admin API, with the same validation, so either path works. Run it from
`backend/`. It needs `OS_DATABASE_URL` (or `DATABASE_URL`), and `OS_TENANT_ID` if the tenant is not the default.
It exits with 2 when the input is refused and says why.

### 1. See the open confirm tasks

```
python -m scripts.os_supply_fact list
```

Each line shows the task, plan, programme, field, intake, the fact if there is one (id, status, value, source) and
the last research run. With curl:

```
curl -s -H "X-OS-Admin-Token: $OS_ADMIN_TOKEN" "$OS_API/v1/os/facts/open"
```

### 2. Check what research found

```
python -m scripts.os_supply_fact show --programme ovgu-eeit --intake 2027
```

This prints the stored fact (value, status, URL, quote, note) and every reading's evidence: value, quote, URL, cycle
and the reasons it was rejected. The common reasons are:

- `cycle_old:<year>`: the page gives an older semester;
- `quote_not_on_page`: the reader made the quote up or misquoted it;
- `scope_unclear`: the page is not about this programme and is not the university's calendar;
- `single_reading`: only one reading was valid;
- `readings_disagree`: the valid readings found different dates.

Research runs and their cost:

```
curl -s -H "X-OS-Admin-Token: $OS_ADMIN_TOKEN" "$OS_API/v1/os/research/runs?programme=ovgu-eeit"
```

Open the calendar page above and find the first day of lectures for the intake's winter semester. Use the faculty
line that applies to the programme. Copy the line word for word.

### 3. Supply the date

```
python -m scripts.os_supply_fact supply --programme ovgu-eeit --intake 2027 --date 2027-10-11 \
  --url https://www.ovgu.de/unimagdeburg/en/academiccalendar-p-49226.html \
  --quote "Classes: October 11, 2027 - January 28, 2028"
```

- `--status` defaults to `confirmed`. Use `--status unconfirmed --note "..."` for a date you could not check on an
  official page.
- `--tz` defaults to the route playbook's time zone (`Europe/Berlin` for Germany).
- To correct a fact research stored, give its id (from `list` or `show`):
  `python -m scripts.os_supply_fact confirm --fact-id 123 --date ... --url ... --quote ...`.

With curl:

```
curl -s -X POST -H "X-OS-Admin-Token: $OS_ADMIN_TOKEN" -H "Content-Type: application/json" "$OS_API/v1/os/facts" \
  -d '{"scope": "programme", "ref": "ovgu-eeit", "field": "semester_start", "intake_year": 2027,
       "value": {"date": "2027-10-11", "tz": "Europe/Berlin"},
       "quote": "Classes: October 11, 2027 - January 28, 2028",
       "url": "https://www.ovgu.de/unimagdeburg/en/academiccalendar-p-49226.html", "status": "confirmed"}'

curl -s -X POST -H "X-OS-Admin-Token: $OS_ADMIN_TOKEN" -H "Content-Type: application/json" \
  "$OS_API/v1/os/facts/123/confirm" \
  -d '{"value": {"date": "2027-10-11", "tz": "Europe/Berlin"}, "quote": "...", "url": "...", "status": "confirmed"}'
```

Either way the waiting confirm tasks are completed and the plans that use the fact are revised: the output lists
the revised plan ids. A confirmed fact needs a quote and a URL. A date that does not parse is refused (422, or
exit code 2).
