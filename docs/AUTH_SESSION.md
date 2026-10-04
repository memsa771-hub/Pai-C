# Placement AI account authentication

Supabase Auth verifies email/password and Google, GitHub, or LinkedIn. Its verified subject maps to a stable PAI `User` through `auth_identities`. PAI then creates an opaque application session and resolves the user's one canonical Student Workspace. Counselor, Vault, and student records remain owned by the workspace; OAuth profile fields do not become student profile facts.

The hosted browser keeps only an HttpOnly `pai_session` cookie. The API stores its SHA-256 hash, user, provider, expiry, and revocation time in `pai_sessions`. The cookie is `Secure` in production, `SameSite=Lax`, and `Path=/`. `GET /v1/auth/session` restores and renews the current session. `DELETE /v1/auth/session` revokes it. Protected `/v1` APIs reject Supabase JWTs as application authority. A revoked session also invalidates stream tickets. A desktop renderer receives a PAI bearer from the session exchange for its native handoff; it uses the same account and workspace. On native provider refresh, exchange rotates the prior PAI bearer in one database transaction.

## Supabase Dashboard and provider consoles

1. Enable Email provider and choose whether email confirmation is required. Configure Supabase Auth's email sender and templates. PAI creates the account session only after Supabase returns a verified identity.
2. Enable Google, GitHub, and LinkedIn OIDC (`linkedin_oidc`) providers in Supabase. Register each provider's client ID and secret **in Supabase**, and register Supabase's callback URL in the corresponding provider console. Never add those secrets to PAI source or `NEXT_PUBLIC_*` variables.
3. Set Supabase Site URL to the deployed app origin. Add `https://app.placement-ai.com/auth/callback` and `https://app.placement-ai.com/auth/reset-password` to allowed redirect URLs. For local development, add the corresponding `http://localhost:3000` URLs (or the port in use). These are PAI return URLs; the external provider callbacks point to Supabase.
4. Enable password recovery in Supabase and use the same reset-password redirect URL. Recovery uses Supabase's code exchange and password update, with no PAI reset token.

## Environment

Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` on the backend and use those same public values as frontend build inputs. Set `NEXT_PUBLIC_API_URL` to the API origin. `CORS_ORIGINS` must contain the exact hosted app origin (`https://app.placement-ai.com` in production). The desktop origin `pai://workspace` is separately allowed. `PAI_SESSION_TTL_SECONDS` defaults to 1209600 seconds (14 days). Production requires HTTPS for the `Secure` cookie. Do not put a Supabase service role key or provider client secret in the frontend.

Keep `REDIS_URL` configured and Redis healthy for the shared username sign-in and availability budgets. Those endpoints fail closed if a configured Redis limiter is unavailable; Supabase owns rate limiting for direct email/password and social authentication.

Run Alembic migration `077_auth_sessions` before deploying the new backend/frontend together. It adds session and identity tables and backfills identities from `users.supabase_uid`; existing user IDs, workspace ownership, and student data remain in place. Old browser `localStorage` Supabase sessions are removed on first load; the student signs in again once.

## Operational checks

Test one email/password and one social sign-in in the configured Supabase project, confirm that all methods return to the existing workspace, then test recovery and confirmation links. After logout, replay the old cookie and old Supabase access token against a protected API: both must be rejected. Test browser Back and a second tab. OAuth availability depends on the provider console and Supabase dashboard configuration; local unit tests cannot prove a production provider is enabled.
