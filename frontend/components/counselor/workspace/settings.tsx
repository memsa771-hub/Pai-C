"use client";
import { useState } from "react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { workspaceApi } from "@/lib/api";
import { Heading } from "./resource";
import copy from "./copy.json";
import entry from "./settings-data.json";

export function CounselorSettings({ base }: { base: string }) {
  const { theme, setTheme } = useTheme();
  const [error, setError] = useState(false),
    [saved, setSaved] = useState(false),
    [deleting, setDeleting] = useState(false),
    [confirmDelete, setConfirmDelete] = useState(false),
    [busy, setBusy] = useState(false);
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
      setSaved(true);
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
    } catch {
      setError(true);
    }
  }
  return (
    <>
      <Heading title={copy.settingsTitle} description={copy.tagline} />
      <div className="grid gap-5 md:grid-cols-2">
        <section className="rounded-2xl border bg-card p-6">
          <h2 className="mb-4 text-lg font-semibold">{copy.theme}</h2>
          <div className="flex flex-wrap gap-2">
            {(["light", "dark", "system"] as const).map((value) => (
              <Button
                key={value}
                variant={theme === value ? "primary" : "outline"}
                aria-pressed={theme === value}
                onClick={() => setTheme(value)}
              >
                {copy[value]}
              </Button>
            ))}
          </div>
        </section>
        <section className="rounded-2xl border bg-card p-6">
          <h2 className="mb-4 text-lg font-semibold">{copy.replyLanguage}</h2>
          <div className="flex gap-2">
            {entry.languages.map((option) => (
              <Button
                variant="outline"
                key={option.value}
                onClick={() => language(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
          {saved && (
            <p role="status" className="mt-3 text-sm text-primary">
              {copy.saved}
            </p>
          )}
        </section>
      </div>
      <section className="mt-6 rounded-2xl border bg-card p-6">
        <h2 className="mb-3 text-xl font-semibold">{copy.privacy}</h2>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          {copy.privacyHelp}
          <span className="mt-2 block">{copy.exportScope}</span>
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Button variant="outline" onClick={download}>
            {copy.export}
          </Button>
          <Button variant="outline" onClick={() => setDeleting(true)}>
            {copy.deleteAccount}
          </Button>
          <a
            className="rounded-lg border px-4 py-2 text-sm"
            href={`${base}/settings/integrations`}
          >
            {copy.integrations}
          </a>
          <a
            className="rounded-lg border px-4 py-2 text-sm"
            href={`${base}/settings/preferences`}
          >
            {copy.notificationSettings}
          </a>
        </div>
        {deleting && (
          <div className="mt-6 rounded-xl border border-destructive/30 p-4">
            <p className="text-sm">{copy.deleteHelp}</p>
            <label className="my-4 flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={confirmDelete}
                onChange={(e) => setConfirmDelete(e.target.checked)}
              />
              {copy.deleteConfirm}
            </label>
            <Button
              disabled={!confirmDelete || busy}
              variant="outline"
              onClick={remove}
            >
              {copy.deleteNow}
            </Button>
            <Button variant="ghost" onClick={() => setDeleting(false)}>
              {copy.cancel}
            </Button>
          </div>
        )}
        {error && (
          <p className="mt-3 text-destructive" role="alert">
            {copy.error}
          </p>
        )}
      </section>
    </>
  );
}
