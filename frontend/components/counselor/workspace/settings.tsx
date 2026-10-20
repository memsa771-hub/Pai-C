"use client";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Bell, Check, ChevronRight, Download, Languages, Link2, Monitor, Moon, Palette, ShieldCheck, Sun, Trash2, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/pai";
import { workspaceApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Heading } from "./resource";
import copy from "./copy.json";
import entry from "./settings-data.json";

const THEMES = [
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
  { value: "system", icon: Monitor },
] as const;
const option = (on: boolean) => cn(
  "flex min-h-12 items-center gap-2.5 rounded-2xl border-2 px-4 py-3 text-sm font-semibold transition-colors",
  on ? "border-brand bg-brand-soft text-brand-ink" : "border-border bg-card hover:border-brand/40",
);

export function CounselorSettings({ base }: { base: string }) {
  const { theme, setTheme } = useTheme();
  const [error, setError] = useState(false),
    [savedLanguage, setSavedLanguage] = useState<string | null>(null),
    [deleting, setDeleting] = useState(false),
    [confirmDelete, setConfirmDelete] = useState(false),
    [busy, setBusy] = useState(false),
    [exported, setExported] = useState(false),
    [currentLanguage, setCurrentLanguage] = useState<string | null>(null);
  // Show the language PAI uses now; a failed read just leaves none selected.
  useEffect(() => {
    let alive = true;
    Promise.resolve().then(() => workspaceApi.getProfileCards()).then((result) => {
      const card = result?.cards?.find((c) => c.key === "preferences.preferred_language");
      if (alive && typeof card?.value === "string") setCurrentLanguage(card.value);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  async function remove() {
    if (!confirmDelete) return;
    setBusy(true);
    try {
      await workspaceApi.deleteMyAccount();
      window.location.assign("/sign-in");
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  async function language(value: string) {
    try {
      const result = await workspaceApi.editStudentProfile({
        fieldKey: "preferences.preferred_language",
        value,
        reason: copy.replyLanguage,
      });
      if (!result.saved) throw new Error();
      setSavedLanguage(value);
      setCurrentLanguage(value);
    } catch {
      setError(true);
    }
  }
  async function download() {
    try {
      const data = await workspaceApi.exportCounselorData();
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
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
  const linkRow = (href: string, label: string, Icon: typeof Bell) => (
    <a href={href} className="flex min-h-14 items-center gap-3 rounded-2xl px-3 transition-colors hover:bg-muted">
      <span aria-hidden className="flex size-9 items-center justify-center rounded-xl bg-muted"><Icon className="size-[18px]" /></span>
      <span className="flex-1 text-sm font-semibold">{label}</span>
      <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
    </a>
  );
  const languageLabel = entry.languages.find((l) => l.value === savedLanguage)?.label;
  return (
    <>
      <Heading title={copy.settingsTitle} description={copy.settings.intro} icon={Palette} tone="violet" />
      {error && (
        <p className="mb-5 flex items-center gap-2 rounded-2xl bg-danger-soft px-4 py-3 text-sm font-medium text-danger-ink" role="alert">
          <TriangleAlert aria-hidden className="size-4 shrink-0" />{copy.error}
        </p>
      )}
      <div className="grid gap-5 lg:grid-cols-2">
        <SectionCard title={copy.theme} description={copy.settings.themeHelp} icon={Palette} tone="violet">
          <div className="grid grid-cols-3 gap-2">
            {THEMES.map(({ value, icon: Icon }) => (
              <button key={value} type="button" aria-pressed={theme === value} onClick={() => setTheme(value)}
                className={cn(option(theme === value), "flex-col justify-center text-center")}>
                <Icon aria-hidden className="size-5" />
                {copy[value]}
              </button>
            ))}
          </div>
        </SectionCard>
        <SectionCard title={copy.replyLanguage} description={copy.settings.languageHelp} icon={Languages} tone="teal">
          <div className="grid gap-2 sm:grid-cols-2">
            {entry.languages.map((item) => (
              <button type="button" key={item.value} aria-pressed={currentLanguage === item.value}
                className={option(currentLanguage === item.value)} onClick={() => language(item.value)}>
                {item.label}
                {currentLanguage === item.value && <Check aria-hidden className="ms-auto size-4" />}
              </button>
            ))}
          </div>
          {languageLabel && (
            <p role="status" className="mt-3 text-sm font-medium text-success-ink">
              {copy.settings.languageSaved.replace("{language}", languageLabel)}
            </p>
          )}
        </SectionCard>
        <SectionCard title={copy.settings.notificationsTitle} description={copy.settings.notificationsHelp} icon={Bell} tone="amber">
          <div className="-mx-3">
            {linkRow(`${base}/settings/preferences`, copy.notificationSettings, Bell)}
            {linkRow(`${base}/settings/integrations`, copy.integrations, Link2)}
          </div>
        </SectionCard>
        <SectionCard title={copy.privacy} icon={ShieldCheck} tone="blue">
          <p className="text-sm leading-relaxed text-muted-foreground">{copy.privacyHelp}</p>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{copy.exportScope}</p>
          <Button size="tap" variant="soft" className="mt-4" onClick={download}>
            <Download aria-hidden />{copy.export}
          </Button>
          {exported && (
            <p role="status" className="mt-3 flex items-center gap-2 text-sm font-medium text-success-ink">
              <Check aria-hidden className="size-4 shrink-0" />{copy.settings.exported}
            </p>
          )}
        </SectionCard>
      </div>
      <section aria-labelledby="danger-title" className="mt-5 rounded-3xl border border-danger/30 bg-card p-5 shadow-soft sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span aria-hidden className="flex size-9 items-center justify-center rounded-xl bg-danger-soft text-danger-ink"><Trash2 className="size-[18px]" /></span>
            <div>
              <h2 id="danger-title" className="font-semibold">{copy.settings.dangerTitle}</h2>
              <p className="text-sm text-muted-foreground">{copy.settings.dangerHelp}</p>
            </div>
          </div>
          {!deleting && <Button size="tap" variant="outline" className="border-danger/40 text-danger-ink" onClick={() => setDeleting(true)}>{copy.deleteAccount}</Button>}
        </div>
        {deleting && (
          <div className="mt-5 rounded-2xl bg-danger-soft p-4 text-danger-ink">
            <p className="text-sm">{copy.deleteHelp}</p>
            <label className="mt-4 flex min-h-11 cursor-pointer items-start gap-3 text-sm font-medium">
              <input
                type="checkbox"
                className="mt-0.5 size-5 shrink-0 accent-[var(--danger)]"
                checked={confirmDelete}
                onChange={(e) => setConfirmDelete(e.target.checked)}
              />
              {copy.deleteConfirm}
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="tap" variant="destructive" disabled={!confirmDelete || busy} onClick={remove}>
                {copy.deleteNow}
              </Button>
              <Button size="tap" variant="ghost" onClick={() => { setDeleting(false); setConfirmDelete(false); }}>
                {copy.cancel}
              </Button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
