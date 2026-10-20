"use client";
import { useCallback, useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import copy from "./copy.json";
import { formatDate } from "@/lib/i18n/format";
import { DEFAULT_LOCALE } from "@/lib/i18n/locales";
import { EmptyState, ErrorState, PageHeader, Skeletons, type Tone } from "@/components/pai";
export { evidenceText as human, evidenceLabel } from "@/lib/evidence-text";

export function useResource<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(false),
    [busy, setBusy] = useState(true);
  const refresh = useCallback(async () => {
    setBusy(true);
    setError(false);
    try {
      setData(await load());
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }, [load]);
  useEffect(() => {
    let alive = true;
    setData(null);
    setBusy(true);
    load()
      .then((value) => {
        if (alive) {
          setData(value);
          setError(false);
        }
      })
      .catch(() => {
        if (alive) setError(true);
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [load]);
  return { data, error, busy, refresh };
}
export function LoadState({
  error,
  busy,
  retry,
  skeleton = "cards",
  empty,
}: {
  error: boolean;
  busy: boolean;
  retry: () => void;
  skeleton?: "cards" | "list" | "profile" | "chat";
  empty?: { title: string; description?: string; icon?: LucideIcon; action?: React.ReactNode };
}) {
  if (error) return <ErrorState retryLabel={copy.retry} onRetry={retry} />;
  if (busy) return <Skeletons variant={skeleton} label={copy.loading} />;
  return <EmptyState title={empty?.title || copy.emptyTitle} description={empty?.description || copy.empty}
    icon={empty?.icon} action={empty?.action} />;
}
export function Heading({
  title,
  description,
  action,
  icon,
  tone,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
}) {
  return <PageHeader title={title} description={description} action={action} icon={icon} tone={tone} />;
}
/** "12 Oct 2026" in the app locale; empty for a missing or invalid date. */
export function shortDate(value: string | null | undefined) {
  return formatDate(value, DEFAULT_LOCALE, { day: "numeric", month: "short", year: "numeric",
    ...(value?.length === 10 ? { timeZone: "UTC" } : {}) });
}
