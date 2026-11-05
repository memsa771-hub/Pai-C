/** Small helpers for the choice screens: what the API said when it refused, and a country's name from its ISO code. */

/** `API 409: {"detail":"..."}` becomes status 409 and the detail text. Anything else has no detail. */
export function apiError(error: unknown): { status: number | null; detail: string } {
  const message = error instanceof Error ? error.message : "";
  const match = /^API (\d{3}): ([\s\S]*)$/.exec(message);
  if (!match) return { status: null, detail: "" };
  let detail = "";
  try {
    const body = JSON.parse(match[2]);
    detail = typeof body?.detail === "string" ? body.detail : "";
  } catch { /* not JSON: no detail */ }
  return { status: Number(match[1]), detail };
}

export const VAULT_DOB_DETAIL = "Confirm your date of birth in your Vault first";
export const UNDER_18_DETAIL = "under 18";

/** A country's name from its ISO code, or the code itself when the runtime has no name. The API may send a name. */
export function placeName(code: string, name?: string): string {
  if (name) return name;
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) || code;
  } catch {
    return code;
  }
}

/** "winter_main" -> "Winter main". */
export const termLabel = (term: string) => {
  const text = term.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** Age in whole years on `today`, from YYYY-MM-DD; null if the text is not a full date. */
export function ageOf(dob: string, today = new Date()): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dob);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]) - 1, Number(m[3])];
  let age = today.getFullYear() - y;
  if (today.getMonth() < mo || (today.getMonth() === mo && today.getDate() < d)) age--;
  return age;
}
