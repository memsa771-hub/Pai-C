"use client";
/** Consent on a chosen route: the state with give / withdraw, and the guardian link sent again.
 * The consent text itself is never here; it comes from the API on the choice screens. */
import { useState } from "react";
import { Check, Loader2, Mail, ShieldCheck, TriangleAlert } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { RouteChoice } from "@/lib/roadmap";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiError } from "./choice-text";
import copy from "./copy.json";

const t = copy.roadmap.choice.consentState;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const FIELD = "h-11 w-full rounded-xl border border-input bg-background px-3 text-sm aria-invalid:border-danger focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/30";

/** Asks again for the guardian's address (it is not kept for a resend) and sends the link. */
export function GuardianResend({ prompt, onSent }: { prompt?: string; onSent?: () => void }) {
  const [email, setEmail] = useState(""), [busy, setBusy] = useState(false), [sent, setSent] = useState(false),
    [error, setError] = useState("");
  async function send() {
    const address = email.trim();
    if (!EMAIL.test(address)) { setError(t.resendRequired); document.getElementById("guardian-resend-email")?.focus(); return; }
    setBusy(true); setError("");
    try {
      await workspaceApi.resendGuardian(address);
      setSent(true);
      onSent?.();
    } catch (e) {
      const { status } = apiError(e);
      setError(status === 429 ? t.rate : status === 409 && apiError(e).detail ? apiError(e).detail : t.error);
    } finally { setBusy(false); }
  }
  return (
    <div className="mt-3 rounded-2xl bg-background p-4 ring-1 ring-border">
      {prompt && <p className="mb-3 flex items-start gap-2 text-sm"><TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />{prompt}</p>}
      <label htmlFor="guardian-resend-email" className="text-sm font-medium">{t.resendLabel}</label>
      <input id="guardian-resend-email" type="email" autoComplete="off" value={email} className={cn(FIELD, "mt-1")}
        aria-invalid={error && !sent ? true : undefined} aria-describedby={error ? "guardian-resend-error" : undefined}
        onChange={(e) => { setEmail(e.target.value); setSent(false); }} />
      {error && <p id="guardian-resend-error" role="alert" className="mt-2 text-sm font-medium text-danger-ink">{error}</p>}
      {sent && <p role="status" className="mt-2 flex items-center gap-1.5 text-sm font-medium"><Check aria-hidden className="size-4" />{t.resendSent}</p>}
      <Button size="tap" variant="soft" className="mt-3" disabled={busy} onClick={send}>
        {busy ? <Loader2 aria-hidden className="animate-spin" /> : <Mail aria-hidden />}{t.resendSend}
      </Button>
    </div>
  );
}

/** Who has agreed, in words (never colour alone), with withdraw / give and the guardian status. */
export function ConsentPanel({ choice, onChange }: { choice: RouteChoice; onChange: (next: RouteChoice) => void }) {
  const [confirming, setConfirming] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""),
    [resend, setResend] = useState(false), [prompt, setPrompt] = useState(false);
  const { student, guardian } = choice.consent;
  async function change(action: "withdraw" | "give") {
    setBusy(true); setError("");
    try {
      const answer = action === "withdraw" ? await workspaceApi.withdrawConsent() : await workspaceApi.giveConsent();
      if (answer.choice) onChange(answer.choice);
      if (action === "give" && answer.choice?.consent.guardian === "missing") { setPrompt(true); setResend(true); }
      if (action === "withdraw") { setPrompt(false); setResend(false); }
    } catch (e) {
      const { status, detail } = apiError(e);
      setError(status === 409 && /not approved/i.test(detail) ? t.textNotReady : t.error);
    } finally { setBusy(false); setConfirming(false); }
  }
  const studentWord = student === "given" ? t.studentGiven : t.studentMissing;
  const guardianWord = guardian === "given" ? t.guardianGiven : guardian === "missing" ? t.guardianMissing : t.guardianNotNeeded;
  return (
    <section aria-labelledby="consent-title" className="mt-4 rounded-2xl bg-background p-4 ring-1 ring-border">
      <h3 id="consent-title" className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck aria-hidden className="size-4 text-primary" />{t.title}</h3>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">{t.student}</dt>
        <dd className="font-semibold" data-state={student}>{studentWord}</dd>
        {guardian !== "not_needed" && (<>
          <dt className="text-muted-foreground">{t.guardian}</dt>
          <dd className="font-semibold" data-state={guardian}>{guardianWord}</dd>
        </>)}
      </dl>
      {student === "missing" && <p className="mt-2 text-sm text-muted-foreground">{t.pausedNote}</p>}
      {!choice.os_supported && <p className="mt-2 text-sm text-muted-foreground">{t.notSupported}</p>}
      {student === "given" && guardian === "missing" && !prompt && <p className="mt-2 text-sm text-muted-foreground">{t.waiting}</p>}
      {error && <p role="alert" className="mt-2 text-sm font-medium text-danger-ink">{error}</p>}
      {confirming ? (
        <div className="mt-3">
          <p className="text-sm">{t.withdrawConfirm}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="tap" variant="destructive" disabled={busy} onClick={() => change("withdraw")}>{t.withdrawYes}</Button>
            <Button size="tap" variant="ghost" onClick={() => setConfirming(false)}>{t.withdrawNo}</Button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {student === "given"
            ? <Button size="tap" variant="ghost" onClick={() => setConfirming(true)}>{t.withdraw}</Button>
            : <Button size="tap" variant="soft" disabled={busy} onClick={() => change("give")}>{t.give}</Button>}
          {student === "given" && guardian === "missing" && !resend &&
            <Button size="tap" variant="soft" onClick={() => setResend(true)}><Mail aria-hidden />{t.resend}</Button>}
        </div>
      )}
      {resend && student === "given" && guardian === "missing" && (
        <GuardianResend prompt={prompt ? t.resendPrompt : undefined} onSent={() => setPrompt(false)} />
      )}
    </section>
  );
}
