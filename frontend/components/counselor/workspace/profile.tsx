"use client";
import { useState } from "react";
import { workspaceApi } from "@/lib/api";
import type {
  LivingPicture,
  ProfileCard,
  EvidenceItem,
} from "@/lib/counselor-workspace";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import copy from "./copy.json";
import { Heading, LoadState, useResource, human } from "./resource";
const load = async () => {
  const [picture, cards] = await Promise.all([
    workspaceApi.getCounselorWorkspace(),
    workspaceApi.getProfileCards(),
  ]);
  return { picture, cards: cards.cards };
};
export function CoverageWheel({
  coverage,
}: {
  coverage: LivingPicture["coverage"];
}) {
  const areas = Object.entries(copy.areas);
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg
        viewBox="0 0 160 160"
        className="size-40 shrink-0"
        role="img"
        aria-label={copy.coverage}
      >
        {areas.map(([key, label], index) => {
          const start = ((index * 36 - 90) * Math.PI) / 180,
            end = (((index + 1) * 36 - 93) * Math.PI) / 180;
          return (
            <path
              key={key}
              d={`M ${80 + 60 * Math.cos(start)} ${80 + 60 * Math.sin(start)} A 60 60 0 0 1 ${80 + 60 * Math.cos(end)} ${80 + 60 * Math.sin(end)}`}
              fill="none"
              stroke="currentColor"
              strokeWidth="18"
              className={coverage[key]?.covered ? "text-primary" : "text-muted"}
            >
              <title>{label}</title>
            </path>
          );
        })}
        <circle
          cx="80"
          cy="80"
          r="25"
          fill="none"
          stroke="currentColor"
          className="text-primary/20"
        />
      </svg>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2">
        {areas.map(([key, label]) => (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span
              className={`size-2 rounded-full ${coverage[key]?.covered ? "bg-primary" : "bg-muted"}`}
            />
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}
export function CertaintyChart({
  ratings,
}: {
  ratings: LivingPicture["ratings"];
}) {
  const points = ratings
    .flatMap((row) => [row.before, row.after])
    .filter((n): n is number => n !== null);
  if (!points.length)
    return <p className="text-sm text-muted-foreground">{copy.empty}</p>;
  return (
    <svg
      viewBox="0 0 300 110"
      role="img"
      aria-label={`${copy.certainty}: ${points.join(", ")}`}
      className="h-28 w-full"
    >
      <path
        d="M10 10 V95 H290"
        stroke="currentColor"
        fill="none"
        className="text-muted"
      />
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        className="text-primary"
        points={points
          .map(
            (n, i) =>
              `${10 + (i * 280) / Math.max(1, points.length - 1)},${95 - n * 8}`,
          )
          .join(" ")}
      />
      {points.map((n, i) => (
        <circle
          key={i}
          cx={10 + (i * 280) / Math.max(1, points.length - 1)}
          cy={95 - n * 8}
          r="4"
          fill="currentColor"
          className="text-primary"
        />
      ))}
    </svg>
  );
}
function ValueEditor({
  value,
  onChange,
  label,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  label: string;
}) {
  if (value && typeof value === "object")
    return (
      <div className="space-y-2">
        {Object.entries(value).map(([key, item]) => (
          <ValueEditor
            key={key}
            label={key.replaceAll("_", " ")}
            value={item}
            onChange={(next) =>
              onChange(
                Array.isArray(value)
                  ? value.map((v, i) => (String(i) === key ? next : v))
                  : { ...value, [key]: next },
              )
            }
          />
        ))}
      </div>
    );
  if (typeof value === "boolean")
    return (
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={value}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
    );
  return (
    <label className="block text-xs text-muted-foreground">
      {label}
      <Input
        className="mt-1"
        value={value === null ? "" : String(value)}
        type={typeof value === "number" ? "number" : "text"}
        onChange={(e) =>
          onChange(
            typeof value === "number" ? Number(e.target.value) : e.target.value,
          )
        }
      />
    </label>
  );
}
export function EvidenceCard({
  card,
  onSaved,
}: {
  card: ProfileCard;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false),
    [removing, setRemoving] = useState(false),
    [value, setValue] = useState(card.value),
    [text, setText] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  async function review(action: "confirm" | "edit" | "remove") {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.reviewProfileCard(card, {
        submission_id: crypto.randomUUID(),
        action,
        expected_digest: card.digest,
        value: action === "edit" ? value : null,
        text,
      });
      setEditing(false);
      onSaved();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="rounded-xl border bg-card p-4">
      <summary className="cursor-pointer list-none">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs capitalize text-muted-foreground">
              {card.key.replaceAll("_", " ").replaceAll(".", " · ")}
            </p>
            <p className="mt-2 break-words text-sm leading-relaxed">
              {human(card.value)}
            </p>
          </div>
          <span className="rounded-full bg-primary/10 px-2 py-1 text-xs text-primary">
            {copy.evidence[card.evidence_level]}
          </span>
        </div>
      </summary>
      <div className="mt-4 space-y-3 border-t pt-4">
        <p className="text-xs font-medium">{copy.source}</p>
        <p className="break-words text-xs text-muted-foreground">
          {human(card.source)}
        </p>
        {editing && (
          <>
            <ValueEditor value={value} onChange={setValue} label={card.key} />
            <Textarea
              aria-label={copy.explainEdit}
              placeholder={copy.explainEdit}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </>
        )}
        {removing && (
          <div className="rounded-lg border border-destructive/30 p-3">
            <p className="mb-3 text-sm">{copy.removeHelp}</p>
            <Button
              disabled={busy}
              variant="outline"
              onClick={() => review("remove")}
            >
              {copy.removeConfirm}
            </Button>
            <Button variant="ghost" onClick={() => setRemoving(false)}>
              {copy.cancel}
            </Button>
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {copy.error}
          </p>
        )}
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button
                disabled={busy || !text.trim()}
                onClick={() => review("edit")}
              >
                {copy.save}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)}>
                {copy.cancel}
              </Button>
            </>
          ) : (
            <>
              <Button disabled={busy} onClick={() => review("confirm")}>
                {copy.confirm}
              </Button>
              <Button variant="outline" onClick={() => setEditing(true)}>
                {copy.edit}
              </Button>
              <Button variant="ghost" onClick={() => setRemoving(true)}>
                {copy.remove}
              </Button>
            </>
          )}
        </div>
      </div>
    </details>
  );
}
function Items({ title, items }: { title: string; items: EvidenceItem[] }) {
  return (
    <section className="rounded-2xl border bg-card p-6">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      {!items.length ? (
        <p className="text-sm text-muted-foreground">{copy.empty}</p>
      ) : (
        <ul className="space-y-4">
          {items.map((item, i) => (
            <li
              key={item.id || i}
              className="border-l-2 border-primary/30 pl-3"
            >
              <p className="text-sm">
                {human(
                  item.value || [
                    item.role,
                    item.wish,
                    item.worry || item.concern,
                  ],
                )}
              </p>
              {item.evidence && (
                <p className="mt-1 text-xs text-muted-foreground">
                  “{item.evidence}”
                </p>
              )}
              {item.kind && <span className="mt-2 mr-2 inline-block rounded-full border px-2 py-1 text-xs">{copy.evidenceKinds[item.kind as keyof typeof copy.evidenceKinds]}</span>}
              {item.category && <p className="mt-1 text-xs text-muted-foreground">{copy.whoseWish}: {copy.wishSources[item.category as keyof typeof copy.wishSources] || item.category}</p>}
              {item.capability_status && (
                <span className="mt-2 inline-block rounded-full bg-muted px-2 py-1 text-xs">
                  {copy.capabilityLabels[item.capability_status as keyof typeof copy.capabilityLabels]}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
export function LivingProfile({
  onChat,
}: {
  onChat: (topic?: string) => void;
}) {
  const resource = useResource(load);
  if (!resource.data || resource.error)
    return (
      <LoadState
        error={resource.error}
        busy={resource.busy}
        retry={resource.refresh}
      />
    );
  const { picture, cards } = resource.data;
  const skills = Array.isArray(picture.capabilities)
    ? picture.capabilities
    : Object.values(picture.capabilities).flat();
  const identity = cards.filter((card) =>
    ["identity.full_name", "location.current_city"].includes(card.key),
  );
  const education = cards.filter(c => c.kind === 'education');
  const currentEducation = education.find(c => (c.value as Record<string, unknown>)?.academic_status === 'current') || education[0];
  const level = (currentEducation?.value as Record<string, unknown>)?.qualification_name;
  const datedCards = [...cards].sort((a,b)=>{
    const date = (card: ProfileCard) => {
      const value = card.value as Record<string, unknown> | null;
      return typeof value?.start_date === 'string' ? value.start_date : typeof value?.end_date === 'string' ? value.end_date : '9999';
    };
    return date(a).localeCompare(date(b));
  });
  return (
    <>
      <Heading
        title={copy.profileTitle}
        description={copy.profileIntro}
        action={
          <Button variant="outline" onClick={resource.refresh}>
            {copy.refresh}
          </Button>
        }
      />
      <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        {typeof level === "string" && <span className="rounded-full border bg-card px-4 py-2">{level}</span>}
        {identity.map((card) => (
          <span key={card.id} className="rounded-full border bg-card px-4 py-2">
            {human(card.value)}
          </span>
        ))}
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        <section className="rounded-2xl border bg-card p-6">
          <h2 className="mb-4 font-semibold">{copy.coverage}</h2>
          <CoverageWheel coverage={picture.coverage} />
          <p className="mt-4 text-xs text-muted-foreground">
            {copy.coverageHelp}
          </p>
        </section>
        <section className="rounded-2xl border bg-card p-6">
          <h2 className="font-semibold">{copy.certainty}</h2>
          <CertaintyChart ratings={picture.ratings} />
          {picture.ratings.length > 0 && (
            <p className="text-sm text-muted-foreground">
              {copy.understood}: {picture.ratings.at(-1)?.understood}/5
            </p>
          )}
        </section>
      </div>
      {picture.picture && (
        <section className="my-5 rounded-2xl border border-primary/20 bg-primary/5 p-6">
          <h2 className="mb-4 text-xl font-semibold">{copy.picture}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {Object.entries(picture.picture).map(([key, line]) => (
              <div key={key}>
                <p className="text-xs font-medium text-primary">
                  {copy.pictureLabels[key as keyof typeof copy.pictureLabels]}
                </p>
                <p className="mt-1 leading-relaxed">{line.text}</p>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="my-6">
        <h2 className="mb-4 text-xl font-semibold">{copy.education}</h2>
        <ol className="space-y-3 border-l-2 border-primary/20 pl-5">
          {datedCards
            .filter((c) =>
              ["education", "course", "test_attempt", "certification"].includes(
                c.key,
              ),
            )
            .map((c) => (
              <li key={c.id}><EvidenceCard card={c} onSaved={resource.refresh} /></li>
            ))}
        </ol>
      </section>
      <div className="grid gap-5 md:grid-cols-2">
        <Items
          title={copy.people}
          items={picture.personal.world.people || []}
        />
        <Items
          title={copy.strengths}
          items={[...picture.personal.self, ...skills]}
        />
        <Items title={copy.interests} items={picture.sections?.interests || []} />
        <Items title={copy.values} items={picture.sections?.values || []} />
        <Items title={copy.limits} items={picture.personal.pressures.items} />
        <Items title={copy.options} items={picture.sections?.options || []} />
        <Items title={copy.goals} items={picture.sections?.goals || picture.personal.source} />
      </div>
      <section className="my-6">
        <h2 className="mb-4 text-xl font-semibold">{copy.review}</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {cards
            .filter(
              (c) =>
                ![
                  "education",
                  "course",
                  "test_attempt",
                  "certification",
                ].includes(c.key),
            )
            .map((c) => (
              <EvidenceCard key={c.id} card={c} onSaved={resource.refresh} />
            ))}
        </div>
      </section>
      <section className="rounded-2xl border border-dashed p-6">
        <h2 className="font-semibold">{copy.missing}</h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {Object.entries(copy.areas)
            .filter(([key]) => !picture.coverage[key]?.covered)
            .map(([key, label]) => (
              <Button key={key} variant="outline" onClick={() => onChat(label)}>
                {label}
              </Button>
            ))}
        </div>
      </section>
    </>
  );
}
