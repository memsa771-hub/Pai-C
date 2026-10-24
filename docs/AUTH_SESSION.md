# Sign-in: Firebase Auth

Firebase Auth is the only identity provider (web now, the mobile app later). Students sign in with email and password or with Google. Hosting stays on our own server; Firebase Hosting is not used.

## How it works

- **Every protected API call carries a Firebase ID token** as `Authorization: Bearer <token>`. The backend verifies it with the Firebase Admin SDK (`backend/app/security/firebase_auth.py`, `human_auth.py`). Nothing a client says about who it is (a user id, an email in a body) is trusted. There are no session cookies.
- **Accounts.** A verified token resolves to the PAI account with that `users.firebase_uid`. On the first verified request the account is created, or the existing account with the same email (and its Vault) is linked.
- **Email verification.** Email/password accounts must verify their address. Until then every protected route answers `403` with the code `AUTH_EMAIL_NOT_VERIFIED`, and the app shows the "check your email" screen. Google accounts arrive verified.
- **Our own emails.** Firebase never sends an email. Verification links, password-reset links and new-sign-in alerts are sent by the backend through Resend (`backend/app/services/auth_emails.py`). Links open `APP_URL/auth/action?mode=verifyEmail|resetPassword&oobCode=…`.
- **Endpoints** (shared with the mobile app):
  - `POST /v1/auth/session`: called after every sign-in with a random per-device id. It links the account and records the device, and a new device sends a sign-in alert (not the account's first device), once per device. Limit: 30 per hour per user.
  - `POST /v1/auth/send-verification`: sends the verification email to the signed-in, unverified account. Limit: 1 per minute and 5 per hour per user.
  - `POST /v1/auth/forgot-password`: sends a reset email. The answer is the same whether or not the account exists. Limit: 3 per hour per email and 10 per hour per IP.
  - `POST /v1/auth/reset-password`: sets the new password from the reset link's code (`oobCode`, `newPassword`), then revokes every session of the account. Limit: 10 per hour per IP.
- **Limits** are all in `backend/app/security/auth_limits.json` and are counted in Redis, so every worker and instance shares one count. Without Redis each process counts on its own. Over a limit the answer is `429 AUTH_RATE_LIMITED`.
- **Signing out** is the client's `signOut` on this device only; no endpoint is called and other devices stay signed in.
- **Revoking every session** happens only after a password reset: Firebase refresh tokens are revoked, and the backend refuses any ID token issued at or before that moment (the moment is kept in Redis for an hour, the life of an ID token).
- **Deleting the account** (`DELETE /v1/account`) needs a sign-in from the last 5 minutes (`403 AUTH_RECENT_SIGN_IN_REQUIRED` otherwise; the app asks the student to sign in again). After one confirmation it deletes every workspace the student owns with everything in it (Vault, memories, files and their bytes, chats, vectors), their channel memberships and their account row; then disables (does not delete) the Firebase user and ends its sessions; then sends the "account deleted" email; the app signs out and opens the landing page. `feedback` rows are kept (their account link is cleared).
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
