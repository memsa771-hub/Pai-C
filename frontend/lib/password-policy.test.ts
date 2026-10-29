import { describe, expect, it } from "vitest";
import { registrationPasswordError } from "./password-policy";
import messages from "./i18n/messages/en-US";

describe("audit #10: the sign-up hint and the check agree", () => {
  it("the hint names letters, numbers and a symbol", () => {
    expect(messages.auth.passwordHint).toMatch(/letters, numbers and a symbol/);
  });
  it("refuses a password without a symbol, number or letter", () => {
    for (const weak of ["Abcdefg1", "abcdefgh!", "12345678!", "Ab1!"]) expect(registrationPasswordError(weak)).toBe("SIGN_UP_WEAK_PASSWORD");
  });
  it("accepts 8+ characters with a letter, a number and a symbol", () => {
    for (const ok of ["abcdef1!", "Lahore2026#", "PAKISTAN9?"]) expect(registrationPasswordError(ok)).toBeNull();
  });
});
