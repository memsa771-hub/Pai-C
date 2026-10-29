"use client";
import { useCallback, useEffect, useState } from "react";
import { useTheme } from "next-themes";
import {
  Bell, Check, Copy, Download, LifeBuoy, Link2, LogOut, Monitor, Moon, Palette, ShieldCheck, Sun, TriangleAlert, UserRound,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useConfirm } from "@/components/ui/dialogs-provider";
import { FeedbackDialog } from "@/components/feedback/feedback-dialog";
import { workspaceApi, type AdminUsage } from "@/lib/api";
import { RecentSignInRequired, requestPasswordReset } from "@/lib/auth/service";
import { signOutAndGoToLanding, signOutAndReturnToSignIn } from "@/lib/auth-redirects";
import { publicAppUrl } from "@/lib/desktop-host";
import { usePaiAuth } from "@/lib/pai-auth-context";
import { useWorkspace } from "@/lib/workspace-context";
import type { ShareSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Heading, LoadState, shortDate, useResource } from "./resource";
import copy from "./copy.json";

const text = copy.settings;
type SectionId = keyof typeof text.sections;
const SECTIONS: { id: SectionId; icon: LucideIcon }[] = [
  { id: "account", icon: UserRound },
  { id: "appearance", icon: Palette },
  { id: "notifications", icon: Bell },
  { id: "privacy", icon: ShieldCheck },
  { id: "help", icon: LifeBuoy },
];
const THEMES = [
  { value: "system", icon: Monitor },
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
] as const;
const fill = (s: string, v: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k) => String(v[k] ?? ""));

/** One setting: what it is and why on the left, its control on the right. */
function Row({ label, help, children, tone }: { label: string; help?: string; children?: React.ReactNode; tone?: "danger" }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-5 py-4 sm:px-6">
      <div className="min-w-0 flex-1 basis-60">
        <p className={cn("text-sm font-semibold", tone === "danger" && "text-danger-ink")}>{label}</p>
        {help && <p className="mt-0.5 max-w-xl text-[13px] leading-relaxed text-muted-foreground">{help}</p>}
      </div>
      {children && <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div className="divide-y divide-border/70 overflow-hidden rounded-[22px] bg-card shadow-card ring-1 ring-border/70">{children}</div>;
}

const usd = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const STAGE_TONE: Record<string, string> = {
  ok: "bg-success-soft text-success-ink",
  research_paused: "bg-warning-soft text-warning-ink",
  paused: "bg-danger-soft text-danger-ink",
};
/** Set once the spend has loaded in this session, i.e. the account is a founder's. */
export const usageSession = { seen: false };
const loadUsage = async () => {
  const data = await workspaceApi.getAdminUsage();
  if (data) usageSession.seen = true;
  return data;
};

/** This month's model spend against the cap (GET /v1/admin/usage). Founder
 * accounts only: for anyone else the API answers 403 and nothing renders. A
 * failed read shows the error only to an account that has loaded it before,
 * so a student never sees a retry for a card that is not theirs. */
export function UsageCard() {
  const usage = useResource<AdminUsage | null>(loadUsage);
  if (usage.error) return usageSession.seen ? <LoadState error busy={false} retry={usage.refresh} skeleton="list" /> : null;
  if (usage.busy || !usage.data) return null;
  const { month, cap, spent, stage, by_role } = usage.data;
  const u = text.usage;
  const share = spent === null || cap <= 0 ? 1 : Math.min(spent / cap, 1);
  return (
    <Panel>
      <Row label={u.title} help={fill(u.help, { month })}>
        <span className={cn("rounded-full px-3 py-1 text-xs font-semibold", STAGE_TONE[stage] || "bg-muted text-foreground")}>
          {u.stages[stage as keyof typeof u.stages] || stage}
        </span>
      </Row>
      <div className="px-5 py-4 sm:px-6">
        <p className="text-sm font-semibold">{spent === null ? u.unread : fill(u.spentOf, { spent: usd.format(spent), cap: usd.format(cap) })}</p>
        <div role="progressbar" aria-label={u.title} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}
          className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full", stage === "paused" ? "bg-danger" : stage === "ok" ? "bg-primary" : "bg-warning")} style={{ width: `${share * 100}%` }} />
        </div>
      </div>
      <div className="px-5 py-4 sm:px-6">
        {by_role.length === 0 ? <p className="text-sm text-muted-foreground">{u.none}</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr><th className="pb-2 font-semibold">{u.role}</th><th className="pb-2 text-right font-semibold">{u.calls}</th><th className="pb-2 text-right font-semibold">{u.cost}</th></tr>
            </thead>
            <tbody>
              {by_role.map((row) => (
                <tr key={row.role} className="border-t border-border/70">
                  <td className="break-all py-2 pr-3">{row.role}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{row.calls}</td>
                  <td className="py-2 text-right tabular-nums">{usd.format(row.est_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}

/** The one Settings place for the student: account, appearance, the
 * notification sound, their data and shared links, and help. Workspace
 * administration (machine tokens, chat-platform bots, agent monitoring)
 * belongs to an operator console, not to a student, and is not here. */
export function CounselorSettings({ onNavigate }: { base?: string; onNavigate?: (view: string) => void }) {
  const { theme, setTheme } = useTheme();
  const { user, signOut } = usePaiAuth();
  const { notificationSound, setNotificationSound } = useWorkspace();
  const confirm = useConfirm();
  const [section, setSection] = useState<SectionId>("account");
  const [error, setError] = useState(false);
  const [reset, setReset] = useState<"idle" | "busy" | "sent" | "failed">("idle");
  const [exported, setExported] = useState(false);
  const [feedback, setFeedback] = useState(false);
  const [shares, setShares] = useState<ShareSummary[] | null>(null);
  const [sharesFailed, setSharesFailed] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false), [needsSignIn, setNeedsSignIn] = useState(false), [busy, setBusy] = useState(false);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("section");
    if (requested && requested in text.sections) setSection(requested as SectionId);
  }, []);
  const choose = (id: SectionId) => {
    setSection(id);
    const q = new URLSearchParams(window.location.search);
    q.set("section", id);
    window.history.replaceState({}, "", `${window.location.pathname}?${q}`);
  };
  const loadShares = useCallback(() => {
    setSharesFailed(false);
    workspaceApi.listShares().then(setShares).catch(() => { setShares([]); setSharesFailed(true); });
  }, []);
  useEffect(() => { if (section === "privacy" && shares === null) loadShares(); }, [section, shares, loadShares]);

  async function sendReset() {
    if (!user?.email) return;
    setReset("busy");
    try { await requestPasswordReset(user.email); setReset("sent"); } catch { setReset("failed"); }
  }
  async function leave() {
    const ok = await confirm({ title: text.signOut, description: text.signOutHelp, confirmText: text.signOut, destructive: true });
    if (ok) await signOutAndReturnToSignIn(signOut);
  }
  async function download() {
    try {
      const data = await workspaceApi.exportCounselorData();
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "my-counselor-data.json";
      link.click();
      URL.revokeObjectURL(url);
      setExported(true);
    } catch {
      setError(true);
    }
  }
  async function stopSharing(share: ShareSummary) {
    try {
      await workspaceApi.deleteShare(share.id);
      setShares((list) => (list || []).filter((s) => s.id !== share.id));
    } catch {
      setError(true);
    }
  }
  async function copyLink(share: ShareSummary) {
    try {
      await navigator.clipboard.writeText(publicAppUrl(`/share/${encodeURIComponent(share.shareToken)}`));
      setCopied(share.id);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      setError(true);
    }
  }
  async function remove() {
    setBusy(true);
    try {
      await workspaceApi.deleteMyAccount();
      await signOutAndGoToLanding(signOut);
    } catch (reason) {
      if (reason instanceof RecentSignInRequired) setNeedsSignIn(true);
      else setError(true);
    } finally {
      setBusy(false);
    }
  }

  const meta = text.sections[section];
  return (
    <>
      <Heading title={copy.settingsTitle} description={text.intro} />
      <div className="grid items-start gap-6 md:grid-cols-[13.5rem_minmax(0,1fr)] lg:gap-10">
        <nav aria-label={text.sectionsLabel} className="flex gap-1 overflow-x-auto pb-1 md:sticky md:top-2 md:flex-col md:overflow-visible md:pb-0">
          {SECTIONS.map(({ id, icon: Icon }) => {
            const on = section === id;
            return (
              <button key={id} type="button" onClick={() => choose(id)} aria-current={on ? "page" : undefined}
                className={cn("relative flex h-11 shrink-0 items-center gap-3 rounded-full px-4 text-sm font-semibold transition-colors",
                  on ? "text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
                {on && <motion.span layoutId="settings-section" aria-hidden className="absolute inset-0 rounded-full bg-brand-soft"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
                <Icon aria-hidden className="relative size-[18px]" />
                <span className="relative whitespace-nowrap">{text.sections[id].label}</span>
              </button>
            );
          })}
        </nav>

        <section aria-labelledby="settings-section-title" className="min-w-0">
          <h2 id="settings-section-title" className="font-display text-xl leading-tight">{meta.title}</h2>
          <p className="mb-4 mt-1 text-sm text-muted-foreground">{meta.description}</p>
          {error && (
            <p className="mb-4 flex items-center gap-2 rounded-2xl bg-danger-soft px-4 py-3 text-sm font-medium text-danger-ink" role="alert">
              <TriangleAlert aria-hidden className="size-4 shrink-0" />{copy.error}
            </p>
          )}

          {section === "account" && (
            <div className="space-y-5">
            <Panel>
              <Row label={text.name} help={text.nameHelp}>
                <span className="text-sm font-semibold">{user?.displayName || "—"}</span>
                {onNavigate && <Button size="tap" variant="outline" onClick={() => onNavigate("profile")}>{text.nameEdit}</Button>}
              </Row>
              <Row label={text.email} help={text.emailHelp}>
                <span className="text-sm font-semibold">{user?.email || "—"}</span>
              </Row>
              <Row label={text.password} help={text.passwordHelp}>
                {reset === "sent"
                  ? <span role="status" className="flex items-center gap-1.5 text-sm font-semibold text-success-ink"><Check aria-hidden className="size-4" />{fill(text.passwordSent, { email: user?.email || "" })}</span>
                  : <Button size="tap" variant="outline" disabled={reset === "busy" || !user?.email} onClick={sendReset}>{text.passwordSend}</Button>}
                {reset === "failed" && <span role="alert" className="text-sm text-danger-ink">{text.passwordFailed}</span>}
              </Row>
              <Row label={text.signOut} help={text.signOutHelp}>
                <Button size="tap" variant="outline" onClick={leave}><LogOut aria-hidden />{text.signOut}</Button>
              </Row>
            </Panel>
            <UsageCard />
            </div>
          )}

          {section === "appearance" && (
            <Panel>
              <Row label={text.theme} help={text.themeHelp}>
                <div role="radiogroup" aria-label={text.theme} className="inline-flex rounded-full bg-background p-1 ring-1 ring-inset ring-border">
                  {THEMES.map(({ value, icon: Icon }) => {
                    const on = (theme || "system") === value;
                    return (
                      <button key={value} type="button" role="radio" aria-checked={on} onClick={() => setTheme(value)}
                        className={cn("flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors",
                          on ? "bg-primary text-primary-foreground" : "text-foreground/75 hover:text-foreground")}>
                        <Icon aria-hidden className="size-4" />{copy[value]}
                      </button>
                    );
                  })}
                </div>
              </Row>
            </Panel>
          )}

          {section === "notifications" && (
            <Panel>
              <Row label={text.soundLabel} help={text.soundHelp}>
                <Switch checked={notificationSound} onCheckedChange={setNotificationSound} aria-label={text.soundLabel} />
              </Row>
            </Panel>
          )}

          {section === "privacy" && (
            <div className="space-y-5">
              <Panel>
                <Row label={text.sharesTitle} help={text.sharesHelp} />
                {shares === null ? (
                  <p className="px-5 py-4 text-sm text-muted-foreground sm:px-6">{text.sharesLoading}</p>
                ) : sharesFailed ? (
                  <p className="px-5 py-4 text-sm text-danger-ink sm:px-6">{text.sharesFailed}</p>
                ) : shares.length === 0 ? (
                  <p className="px-5 py-4 text-sm text-muted-foreground sm:px-6">{text.sharesEmpty}</p>
                ) : shares.map((share) => (
                  <div key={share.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5 sm:px-6">
                    <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-soft text-primary"><Link2 className="size-4" /></span>
                    <div className="min-w-0 flex-1 basis-48">
                      <p className="truncate text-sm font-semibold">{share.title || copy.nav.threads}</p>
                      <p className="text-xs text-muted-foreground">{fill(text.shareMeta, { count: share.messageCount, date: shortDate(share.createdAt) })}</p>
                    </div>
                    <Button size="tap" variant="ghost" onClick={() => copyLink(share)}>
                      {copied === share.id ? <Check aria-hidden /> : <Copy aria-hidden />}{copied === share.id ? text.shareCopied : text.shareCopy}
                    </Button>
                    <Button size="tap" variant="outline" className="border-danger/40 text-danger-ink" onClick={() => stopSharing(share)}>{text.shareStop}</Button>
                  </div>
                ))}
              </Panel>
              <Panel>
                <Row label={text.exportLabel} help={text.exportHelp}>
                  <Button size="tap" variant="outline" onClick={download}><Download aria-hidden />{copy.export}</Button>
                </Row>
                {exported && (
                  <p role="status" className="flex items-center gap-2 px-5 py-3 text-sm font-medium text-success-ink sm:px-6">
                    <Check aria-hidden className="size-4 shrink-0" />{text.exported}
                  </p>
                )}
                <Row label={text.deleteLabel} help={text.deleteHelp} tone="danger">
                  {!deleting && <Button size="tap" variant="outline" className="border-danger/40 text-danger-ink" onClick={() => setDeleting(true)}>{copy.deleteAccount}</Button>}
                </Row>
                {deleting && (
                  <div className="bg-danger-soft px-5 py-4 text-danger-ink sm:px-6">
                    <p className="text-sm">{needsSignIn ? copy.deleteNeedsSignIn : copy.deleteHelp}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {needsSignIn
                        ? <Button size="tap" variant="destructive" onClick={() => void signOutAndReturnToSignIn(signOut)}>{copy.deleteSignInAgain}</Button>
                        : <Button size="tap" variant="destructive" disabled={busy} onClick={remove}>{copy.deleteNow}</Button>}
                      <Button size="tap" variant="ghost" onClick={() => { setDeleting(false); setNeedsSignIn(false); }}>{copy.cancel}</Button>
                    </div>
                  </div>
                )}
              </Panel>
              <p className="flex items-start gap-2 px-1 text-xs text-muted-foreground"><ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />{text.privacyNote}</p>
            </div>
          )}

          {section === "help" && (
            <Panel>
              <Row label={text.feedbackLabel} help={text.feedbackHelp}>
                <Button size="tap" variant="outline" onClick={() => setFeedback(true)}>{text.feedbackAction}</Button>
              </Row>
            </Panel>
          )}
        </section>
      </div>
      {feedback && <FeedbackDialog onClose={() => setFeedback(false)} />}
    </>
  );
}
