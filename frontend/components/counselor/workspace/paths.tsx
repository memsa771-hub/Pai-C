"use client";
import { useCallback, useEffect, useState } from "react";
import { workspaceApi } from "@/lib/api";
import type { Possibility } from "@/lib/possibilities";
import { Button } from "@/components/ui/button";
import { Heading, LoadState, useResource, human } from "./resource";
import copy from "./copy.json";
const list = () => workspaceApi.getPossibilities();
export function PathCard({
  path,
  onOpen,
  onChange,
}: {
  path: Possibility;
  onOpen: () => void;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  async function act(action: "save" | "dismiss") {
    setBusy(true);
    try {
      await workspaceApi.changePossibility(path.id, action);
      onChange();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="flex flex-col rounded-2xl border bg-card p-6 shadow-sm">
      <p className="mb-3 text-xs capitalize text-muted-foreground">
        {path.status}
      </p>
      <h2 className="text-xl font-semibold">{path.title}</h2>
      <p className="mt-4 text-xs font-medium text-primary">{copy.why}</p>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        {path.why}
      </p>
      {path.evidence[0]?.text && (
        <blockquote className="mt-4 border-l-2 pl-3 text-sm">
          “{path.evidence[0].text}”
        </blockquote>
      )}
      {error && (
        <p role="alert" className="mt-3 text-destructive">
          {copy.error}
        </p>
      )}
      <div className="mt-auto flex flex-wrap gap-2 pt-6">
        <Button onClick={onOpen}>{copy.explore}</Button>
        {["suggested", "dismissed"].includes(path.status) && (
          <Button variant="outline" disabled={busy} onClick={() => act("save")}>
            {copy.save}
          </Button>
        )}
        {!["dismissed", "chosen"].includes(path.status) && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => act("dismiss")}
          >
            {copy.notForMe}
          </Button>
        )}
      </div>
    </article>
  );
}
export function Paths({ onOpen }: { onOpen: (id: string) => void }) {
  const resource = useResource(list);
  return (
    <>
      <Heading title={copy.pathsTitle} description={copy.pathsIntro} />
      {!resource.data || resource.error ? (
        <LoadState
          error={resource.error}
          busy={resource.busy}
          retry={resource.refresh}
        />
      ) : !resource.data.length ? (
        <LoadState busy={false} error={false} retry={resource.refresh} />
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {resource.data.map((path) => (
            <PathCard
              path={path}
              key={path.id}
              onOpen={() => onOpen(path.id)}
              onChange={resource.refresh}
            />
          ))}
        </div>
      )}
    </>
  );
}
export function PathPage({
  id,
  onBack,
  onPlaces,
  onChat,
}: {
  id: string;
  onBack: () => void;
  onPlaces: () => void;
  onChat: (text: string) => void;
}) {
  const load = useCallback(() => workspaceApi.getPath(id), [id]);
  const resource = useResource(load);
  const [activityScheduled, setActivityScheduled] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  useEffect(() => {
    if (
      !resource.data ||
      !["pending", "queued", "executing", "planning", "verifying", "running"].includes(
        resource.data.status,
      )
    )
      return;
    const timer = setInterval(resource.refresh, 5000);
    return () => clearInterval(timer);
  }, [resource.data?.status, resource.refresh]);
  async function start() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.changePossibility(id, "explore");
      await resource.refresh();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  if (!resource.data || resource.error)
    return (
      <LoadState
        busy={resource.busy}
        error={resource.error}
        retry={resource.refresh}
      />
    );
  const result = resource.data;
  return (
    <>
      <Button variant="ghost" className="mb-6" onClick={onBack}>
        ← {copy.back}
      </Button>
      <Heading
        title={result.possibility.title}
        description={result.possibility.why}
      />
      {result.status === "stale" && <section className="mb-5 rounded-xl border p-4"><p>{copy.stalePath}</p><Button disabled={busy} onClick={start} className="mt-3">{copy.refresh}</Button>{error && <p role="alert">{copy.error}</p>}</section>}
      {!result.path ? (
        <section className="rounded-2xl border bg-card p-8">
          <p>
            {["not_started", "failed"].includes(result.status)
              ? copy.pathEmpty
              : copy.pathLoading}
          </p>
          {error && <p role="alert">{copy.error}</p>}
          <Button
            className="mt-4"
            disabled={
              busy || !["not_started", "failed"].includes(result.status)
            }
            onClick={start}
          >
            {copy.explore}
          </Button>
        </section>
      ) : (
        <>
          <div className="grid gap-5 md:grid-cols-2">
            {Object.entries(copy.pathSections).map(([key, label]) => (
              <section key={key} className="rounded-2xl border bg-card p-6">
                <h2 className="mb-3 text-lg font-semibold">{label}</h2>
                {human(result.path?.[key]).trim() ? (
                  <p className="whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                    {human(result.path?.[key])}
                  </p>
                ) : result.facts.filter((f) => f.field === key).length ? (
                  result.facts
                    .filter((f) => f.field === key)
                    .map((fact, i) => (
                      <div key={i}>
                        <p>{human(fact.value)}</p>
                        <Source fact={fact} />
                      </div>
                    ))
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {copy.missingResearch}
                  </p>
                )}
              </section>
            ))}
          </div>
          <section className="my-6 rounded-2xl border border-primary/20 bg-primary/5 p-6">
            <h2 className="text-lg font-semibold">{copy.tryIt}</h2>
            <p className="my-3">{human(result.path.try_it)}</p>
            <Button className="mr-3" disabled={busy || activityScheduled} onClick={async()=>{
              setBusy(true);setError(false);
              try {await workspaceApi.acceptPathActivity(id);setActivityScheduled(true);} catch {setError(true);} finally {setBusy(false);}
            }}>{activityScheduled ? copy.activityScheduled : copy.acceptActivity}</Button>
            {error && <p role="alert" className="my-2 text-destructive">{copy.error}</p>}
            <Button variant="outline" onClick={() => onChat(copy.reflection)}>
              {copy.reflection}
            </Button>
          </section>
          <section className="rounded-2xl border bg-card p-6">
            <h2 className="text-xl font-semibold">{copy.places}</h2>
            <p className="my-3 text-muted-foreground">{copy.placesIntro}</p>
            <Button onClick={onPlaces}>{copy.places}</Button>
          </section>
        </>
      )}
    </>
  );
}
function Source({ fact }: { fact: Record<string, unknown> }) {
  const url = String(fact.source_url || "");
  let host = "";
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:") host = parsed.hostname;
  } catch {}
  return (
    <p className="mt-2 text-xs text-muted-foreground">
      {host && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline"
        >
          {host}
        </a>
      )}{" "}
      · {copy.sourceDate}: {String(fact.checked_at || "").slice(0, 10)} ·{" "}
      {fact.status === "verified" ? copy.verified : copy.unconfirmed}
    </p>
  );
}
export function ProgramPage({
  id,
  onBack,
  onCompare,
}: {
  id: string;
  onBack: () => void;
  onCompare?: () => void;
}) {
  const load = useCallback(() => workspaceApi.getPrograms(id), [id]);
  const resource = useResource(load);
  const [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  useEffect(() => {
    if (
      !resource.data ||
      ["not_started", "completed", "failed", "stale"].includes(resource.data.status)
    )
      return;
    const timer = setInterval(resource.refresh, 5000);
    return () => clearInterval(timer);
  }, [resource.data?.status, resource.refresh]);
  async function prepare() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.preparePathRoadmap(id);
      onCompare?.();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  async function search() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.searchPrograms(id);
      await resource.refresh();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="ghost" className="mb-6" onClick={onBack}>
        ← {copy.back}
      </Button>
      <Heading title={copy.places} description={copy.placesIntro} />
      {!resource.data || resource.error ? (
        <LoadState
          busy={resource.busy}
          error={resource.error}
          retry={resource.refresh}
        />
      ) : (
        <>
          {resource.data.status === "not_started" ||
          ["failed", "stale"].includes(resource.data.status) ? (
            <section className="rounded-2xl border bg-card p-6">
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="size-5 accent-primary"
                />
                {copy.placesConsent}
              </label>
              <Button
                disabled={!consent || busy}
                onClick={search}
                className="mt-5"
              >
                {copy.search}
              </Button>
              {error && (
                <p role="alert" className="mt-3 text-destructive">
                  {copy.error}
                </p>
              )}
            </section>
          ) : resource.data.status !== "completed" ? (
            <p role="status">{copy.pathLoading}</p>
          ) : !resource.data.programs.length ? (
            <p className="rounded-2xl border p-6">{copy.noPrograms}</p>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {resource.data.programs.map((program) => (
                <article
                  key={program.opportunity_id}
                  className="rounded-2xl border bg-card p-6"
                >
                  <h2 className="text-xl font-semibold">{program.title}</h2>
                  <Source
                    fact={program as unknown as Record<string, unknown>}
                  />
                  <p className="my-4 rounded-lg bg-muted p-3 text-sm">
                    {copy.eligibility[
                      program.eligibility.label as keyof typeof copy.eligibility
                    ] || copy.eligibility.unknown}
                  </p>
                  {program.fees && Object.keys(program.fees).length > 0 && (
                    <section className="my-4 text-sm">
                      <h3 className="font-semibold">{copy.fees}</h3>
                      <p>{human(program.fees)}</p>
                    </section>
                  )}
                  {program.rules.map((rule, i) => (
                    <div key={i} className="my-3 border-t pt-3 text-sm">
                      <p>{human(rule.value)}</p>
                      <Source fact={rule} />
                    </div>
                  ))}
                  {program.eligibility.route.length > 0 && (
                    <div>
                      <h3 className="font-semibold">{copy.route}</h3>
                      {program.eligibility.route.map((route, i) => (
                        <div key={i}>
                          <p>{human(route.action)}</p>
                          <Source fact={route} />
                        </div>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
          {resource.data.status === "completed" && (
            <section className="mt-6 rounded-2xl border bg-card p-6">
              <p className="mb-3 text-sm text-muted-foreground">
                {copy.decisionPending}
              </p>
              <Button disabled={busy} onClick={prepare}>
                {copy.prepareRoadmap}
              </Button>
              {error && <p role="alert">{copy.error}</p>}
            </section>
          )}
        </>
      )}
    </>
  );
}
