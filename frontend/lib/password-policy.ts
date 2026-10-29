// Was duplicated from packages/launcher/src/shared/account-registration.ts;
// the sign-up hint promises "letters, numbers and a symbol", so the check now
// requires all three (audit #10, the stricter rule kept). Keep the launcher in
// sync when it is next touched.
const SYMBOL = /[!@#$%^&*()_+\-=\[\]{};':"\|,.<>\/?]/

export function registrationPasswordError(password: string): string | null {
  const required = [/[A-Za-z]/, /[0-9]/, SYMBOL]
  if (password.length < 8 || !required.every((pattern) => pattern.test(password)))
    return "SIGN_UP_WEAK_PASSWORD"
  if (["12345678", "password", "qwerty123", "abc12345", "11111111", "00000000"].includes(password.toLowerCase()))
    return "SIGN_UP_WEAK_PASSWORD"
  return null
}
