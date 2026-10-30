# Runbook: pilot email (Slice 9b)

PAI OS emails students reminders about the steps waiting in their inbox (`inbox_reminder`) and asks for their input
when the plan needs it (`replan_request`). Every email is first written to `os_outbox` with an idempotency key
(invariant 8), and the worker's `deliver_outbox` job sends pending rows every minute.

The outbox stores a **student reference** (in the pilot, the workspace id), never an address. The address is looked
up at send time through the host's recipient lookup, then checked against the allow-list. It is never stored in
`os_outbox` or `os_events` and never logged: logs and events show only its SHA-256.

## Email setup

### Settings

Set these on the **worker** (it sends). Set the same values on the API, so that `email-status` reports them.

| setting | meaning |
|---|---|
| `OS_EMAIL_SENDER` | `log` (default: nothing leaves, an `email_logged` event is written; rehearsals use this) or `resend` |
| `OS_RESEND_API_KEY` | The Resend API key. Needed with `resend`. Set it in the server's secret store only: never in chat, logs, tickets or the repo |
| `OS_EMAIL_FROM` | The From address, on the domain verified in Resend. Needed with `resend` |
| `OS_EMAIL_ALLOWLIST` | Comma-separated exact addresses that may receive email. Compared after trimming and lower-casing. Empty means nobody: every row is `blocked` |
| `OS_RECIPIENT_LOOKUP` | `module.path:callable`, the host's lookup (below). Imported when the worker starts. Required with `resend`: without it the worker prints an error naming this setting and exits with code 2 |
| `OS_APP_URL` | The student app's base URL, e.g. `https://app.example.test`. Emails then link to `<OS_APP_URL>/<student ref>/os-inbox`. Unset: no link, the email says to look in the PAI inbox |

`load_settings` refuses `resend` without `OS_RESEND_API_KEY` and `OS_EMAIL_FROM`. The worker then does not start;
the API logs `PAI OS is enabled but not mounted: invalid settings (...)` at ERROR and runs without the OS.

### What the host must provide

The OS never imports host code (invariant 11), so the host supplies the address lookup. One function, used by both
processes:

```python
def recipient_email(student_ref: str) -> str | None:
    """The student's email address, or None when they have none."""
```

- **Mapping (pilot):** `student_ref` is the workspace UUID: workspace -> `owner_user_id` -> `users.email`.
- **No address:** return `None` (or an empty string). The row becomes `blocked` with reason `no_address`.
- **Temporary failure** (database down): raise any exception. The DBOS step retries and the row stays `pending`. The
  exception's text is never stored or logged (only its class name), so it may contain whatever the host likes.
- It is called once per row on each delivery pass, from the worker's thread; it must open and close its own database
  session.

How each process gets it:

- **Worker:** set `OS_RECIPIENT_LOOKUP=<module.path>:recipient_email`. The worker imports it at start, like
  `OS_EXTRA_MODULES`. A path that cannot be imported, or names something not callable, stops the worker.
- **API:** pass it to the mount: `mount_os(app, ..., recipient_lookup=recipient_email)`. `mount_os` hands it to
  `ports.configure`, which sets the `RecipientLookup` port (`backend/app/os/ports/recipients.py`). The API does not
  send email today; the port is there so `email-status` can show it and so later API-side sends use the same lookup.

The host-side change (the function and the `mount_os` argument in `backend/app/main.py`) is a shared-file PR of its
own.

### The allow-list

For the pilot, `OS_EMAIL_ALLOWLIST` stays an explicit list: add each pilot student's address (the one in their PAI
account) once they have agreed to take part. The check runs on the **looked-up** address, so a student whose account
address changes is `blocked` until the list is updated. Rows blocked this way stay `blocked`: they are not retried.

### What happens to a row

| outcome | status | event (`os_events`, `plan_id` null) |
|---|---|---|
| Sent (Resend 2xx) | `sent` | none |
| Lookup found no address | `blocked` | `email_blocked`, `reason: no_address` |
| Address is not an email address | `blocked` | `email_blocked`, `reason: invalid_address`, `to_sha256` |
| Address not on the allow-list | `blocked` | `email_blocked`, `reason: not_on_allowlist`, `to_sha256` |
| Template or payload cannot be rendered | `failed` | `email_failed`, `reason: unrenderable` |
| Resend 400, 404, 409 and other 4xx (not 401/403/408/422/429) | `failed` | `email_failed`, `reason: refused`, `status` |
| **Resend 401, 403 or 422** | stays `pending`; the pass **stops** | one `email_config_error` per pass, with `status`; ERROR log |
| Resend 408, 429, 5xx, network error, or the lookup raised | stays `pending` | none; the DBOS step retries |

401 and 403 mean the key is wrong, revoked or lacks permission; 422 usually means the From address or domain is not
verified. Fix the setting and restart the worker: the waiting rows go out on the next pass, each once (the
idempotency key is also sent to Resend).

### Templates

The texts live in `backend/app/os/outbox/templates.yaml` (plain text, `str.format` placeholders, like the playbook
notes). There is one per reminder slot, worded by urgency: `w` (weekly), `d3` (every 3 days), `d` (daily), `h12`
(due within 48 hours), `esc` (overdue), plus `replan_request`. A reminder shows the step's title and its due date in
the task's own time zone, e.g. "Friday 16 July 2027, 23:59 (Europe/Berlin)". Every email has a greeting, the inbox
link (with `OS_APP_URL`) and a footer saying why the student gets it. Emails never contain student documents or AI
text: the replan request's own words stay in the inbox.

The file is checked when the worker starts: a missing template, an unknown field or a broken placeholder stops it.
`backend/tests/os/test_email_pilot.py` renders every template.

## Reading email-status

```
GET /v1/os/admin/email-status
X-OS-Admin-Token: <admin token>
```

```json
{
  "sender": "resend",
  "lookup_setting": true,
  "lookup_in_api": true,
  "allowlist_size": 12,
  "app_url_set": true,
  "counts": {"pending": 0, "sent": 41, "skipped": 0, "blocked": 1, "failed": 0},
  "last_config_error": {"at": "2027-07-01T09:14:00Z", "status": 401}
}
```

- `sender`, `lookup_setting`, `allowlist_size`, `app_url_set`: the **API's** settings. They match the worker's only if
  both have the same environment.
- `lookup_setting`: `OS_RECIPIENT_LOOKUP` is set (what the worker loads). `lookup_in_api`: the host passed a lookup to
  `mount_os`.
- `counts`: `email` rows in `os_outbox` per status (Counsellor hand-overs are not email and are not counted).
- `last_config_error`: the latest `email_config_error`, or `null`. If its time is recent and `pending` keeps growing,
  delivery is stopped: check the key, the From address and the domain in Resend.

It never shows an address, the key or the lookup's module path. To see why rows were blocked:

```sql
SELECT at, payload->>'reason' AS reason, payload->>'idempotency_key' AS key
FROM os.os_events WHERE type = 'email_blocked' ORDER BY id DESC LIMIT 20;
```

To check whether a given address is the blocked one, compare `payload->>'to_sha256'` with
`sha256(lower(trim(address)))`, computed on your own machine.
