"use client";
import { useCallback, useEffect, useState } from "react";
import copy from "./copy.json";
import { Button } from "@/components/ui/button";

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
}: {
  error: boolean;
  busy: boolean;
  retry: () => void;
}) {
  return (
    <div
      className="rounded-2xl border bg-card p-8 text-center"
      role={error ? "alert" : "status"}
    >
      <p className="text-muted-foreground">
        {error ? copy.error : busy ? copy.loading : copy.empty}
      </p>
      {error && (
        <Button className="mt-4" variant="outline" onClick={retry}>
          {copy.retry}
        </Button>
      )}
    </div>
  );
}
export function Heading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl">
        <p className="mb-2 text-xs font-semibold tracking-widest text-primary">
          {copy.eyebrow}
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          {title}
        </h1>
        <p className="mt-3 leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
      {action}
    </header>
  );
}
export function human(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(human).filter(Boolean).join(" · ");
  if (typeof value === "object")
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key.replaceAll("_", " ")}: ${human(item)}`)
      .join(" · ");
  return String(value);
}
