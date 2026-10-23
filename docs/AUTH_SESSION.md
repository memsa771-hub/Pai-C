# Sign-in: Firebase Auth

Firebase Auth is the only identity provider (web now, the mobile app later). Students sign in with email and password or with Google. Hosting stays on our own server; Firebase Hosting is not used.

## How it works

- **Every protected API call carries a Firebase ID token** as `Authorization: Bearer <token>`. The backend verifies it with the Firebase Admin SDK (`backend/app/security/firebase_auth.py`, `human_auth.py`). Nothing a client says about who it is (a user id, an email in a body) is trusted. There are no session cookies.
- **Accounts.** A verified token resolves to the PAI account with that `users.firebase_uid`. On the first verified request the account is created, or the existing account with the same email (and its Vault) is linked.
- **Email verification.** Email/password accounts must verify their address. Until then every protected route answers `403` with the code `AUTH_EMAIL_NOT_VERIFIED`, and the app shows the "check your email" screen. Google accounts arrive verified.
- **Our own emails.** Firebase never sends an email. Verification links, password-reset links and new-sign-in alerts are sent by the backend through Resend (`backend/app/services/auth_emails.py`). Links open `APP_URL/auth/action?mode=verifyEmail|resetPassword&oobCode=…`.
- **Endpoints** (rate-limited, shared with the mobile app):
  - `POST /v1/auth/session`: called after every sign-in with a random per-device id. It links the account and records the device, and a new device sends a sign-in alert (not the account's first device).
  - `POST /v1/auth/send-verification`: sends the verification email to the signed-in, unverified account.
  - `POST /v1/auth/forgot-password`: sends a reset email. The answer is the same whether or not the account exists.
- **SSE and file URLs** cannot send a header, so they use short-lived read-only stream tickets bound to the account's Firebase uid (`backend/app/security/stream_ticket.py`).

## Firebase console (project "Placement-ai")

1. Create a web app and copy its config into the frontend variables (`NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_APP_ID`; the project id comes from `FIREBASE_PROJECT_ID`).
2. Authentication → Sign-in method: enable **Email/Password** and **Google**.
3. Authentication → Settings → Authorized domains: add `placement-ai.com`, `app.placement-ai.com` and `localhost`.
4. Project settings → Service accounts: generate a key. Save the JSON as `secrets/firebase-service-account.json` (git-ignored); Docker mounts it read-only for the backend. Never commit it.
5. Leave Firebase's own email templates unused: the backend sends every account email through Resend, so `RESEND_API_KEY`, `EMAIL_FROM` (a domain verified in Resend) and `APP_URL` must be set.

## Deploy

Run the Alembic migrations through `114` (adds `users.firebase_uid` and `auth_devices`, and drops the old provider column). Existing accounts and their workspaces stay; each student is linked on their first Firebase sign-in with the same email.

## Local testing

The backend tests run the account flows against the Firebase Auth emulator (`backend/tests/test_firebase_auth.py`, demo project `demo-pai`, skipped when the emulator is not running):

```
firebase emulators:start --only auth --project demo-pai
```

Set `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099` (backend) and `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099` (frontend) to point a local stack at the emulator.
