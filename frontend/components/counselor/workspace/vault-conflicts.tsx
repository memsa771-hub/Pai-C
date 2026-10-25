"use client";
/** The Vault's conflict system: a banner that cannot be missed, a short
 * summary in the side column, and a review dialog that asks one question at
 * a time (VAULT_SPEC §Conflicts). Every card shows only the answers the
 * backend offers it; nothing here blocks the rest of the Vault. */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AlertCircle, ArrowRight, CircleCheck, FileText, History, PencilLine } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import { vaultError, withChoiceLabels, type VaultAnswer, type VaultCatalogType, type VaultConflict, type VaultConflictSource } from "@/lib/vault";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EvidenceBadge, vaultBadgeLabel } from "@/components/pai";
import { cn } from "@/lib/utils";
import copy from "./copy.json";
import { fill, text } from "./profile-parts";
import { human, shortDate } from "./resource";
import { ValueEditor } from "./profile-details";

type Outcome = { answer: VaultAnswer; value?: unknown };
type OpenDocument = ((fileId: string) => void) | null;
const ADVANCE_MS = 1200;

const countLine = (count: number) => (count === 1 ? text.conflictBannerOne : fill(text.conflictBannerMany, { count }));

/** The warm card at the top of the Vault page, above the tabs. */
export function ConflictBanner({ count, onReview }: { count: number; onReview: () => void }) {
  if (!count) return null;
  return (
    <section aria-labelledby="conflict-banner-title"
      className="mt-6 flex flex-wrap items-center gap-4 rounded-2xl border border-warning/40 bg-warning-soft p-4 shadow-soft sm:p-5">
      <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-full bg-card text-warning">
        <AlertCircle className="size-6" />
      </span>
      <div className="min-w-0 basis-48 flex-1">
        <h2 id="conflict-banner-title" className="text-lg font-bold leading-tight text-warning-ink">{countLine(count)}</h2>
        <p className="mt-0.5 text-sm text-warning-ink/90">{text.conflictBannerBody}</p>
      </div>
      <Button size="tap" onClick={onReview} className="max-sm:w-full">
        {text.conflictReviewNow}<ArrowRight aria-hidden />
      </Button>
    </section>
  );
}

/** The side column's "Please check": the count, the first two questions, Review all. */
export function ConflictSummary({ conflicts, onReview }: { conflicts: VaultConflict[]; onReview: (id: string | null) => void }) {
  if (!conflicts.length) return null;
  const rest = conflicts.length - 2;
  return (
    <section aria-labelledby="check-title" className="rounded-2xl border border-warning/40 bg-card p-5 shadow-soft">
      <h2 id="check-title" className="flex items-center gap-2 text-lg font-bold">
        <AlertCircle aria-hidden className="size-5 text-warning" />{text.checkTitle}
        <span className="ms-auto rounded-full bg-warning-soft px-2.5 py-0.5 text-xs font-bold tabular-nums text-warning-ink">{conflicts.length}</span>
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{text.checkIntro}</p>
      <ul className="mt-1 divide-y">
        {conflicts.slice(0, 2).map((conflict) => (
          <li key={conflict.id}>
            <button type="button" onClick={() => onReview(conflict.id)} aria-haspopup="dialog"
              className="group flex min-h-11 w-full items-center gap-2 py-2.5 text-left text-sm font-semibold">
              <span className="min-w-0 flex-1 truncate group-hover:text-primary">{conflict.question}</span>
              <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground group-hover:text-primary" />
            </button>
          </li>
        ))}
      </ul>
      {rest > 0 && <p className="text-xs text-muted-foreground">{fill(text.conflictMore, { count: rest })}</p>}
      <Button size="tap" variant="outline" className="mt-3 w-full" onClick={() => onReview(null)} aria-haspopup="dialog">
        {text.conflictReviewAll}
      </Button>
    </section>
  );
}

/** "You said this · 12 Oct 2026", or the file as a link that opens it in Documents. */
function SourceLine({ source, openDocument }: { source: VaultConflictSource; openDocument: OpenDocument }) {
  const date = shortDate(source.said_on);
  const words = {
    stated: [text.conflictSourceSaid, text.conflictSourceSaidNoDate],
    confirmed: [text.conflictSourceConfirmed, text.conflictSourceConfirmedNoDate],
    inferred: [text.conflictSourceGuess, text.conflictSourceGuessNoDate],
    shown: [text.conflictSourceShown, text.conflictSourceShownNoDate],
  }[source.level];
  const doc = source.document;
  const file = doc && fill(doc.page ? text.conflictSourcePage : text.conflictSourceFile, { filename: doc.filename, page: doc.page ?? "" });
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <EvidenceBadge level={source.level} label={vaultBadgeLabel(source.level)} />
      {doc && openDocument ? (
        <button type="button" onClick={() => openDocument(doc.file_id)} aria-label={fill(text.openDocument, { filename: doc.filename })}
          className="inline-flex min-h-6 min-w-0 items-center gap-1 rounded font-semibold text-primary hover:underline focus-visible:outline-2 focus-visible:outline-ring">
          <FileText aria-hidden className="size-3.5 shrink-0" /><span className="break-all">{file}</span>
        </button>
      ) : doc ? <span className="break-all font-semibold">{file}</span>
        : <span>{date ? fill(words[0], { date }) : words[1]}</span>}
    </div>
  );
}

type Tile = { answer: VaultAnswer; title: string; value: string; source: VaultConflictSource | null };

/** Two big choices as a radio group: Saved and New, or Yes and No for a file. */
function Tiles({ tiles, labelledBy, busy, chosen, onChoose, openDocument }: {
  tiles: Tile[]; labelledBy: string; busy: boolean; chosen: VaultAnswer | null;
  onChoose: (answer: VaultAnswer) => void; openDocument: OpenDocument;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const [focus, setFocus] = useState(0);
  const move = (event: KeyboardEvent, index: number) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + tiles.length) % tiles.length;
    setFocus(next);
    refs.current[next]?.focus();
  };
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} className={cn("-m-1 grid gap-3 p-1", tiles.length > 1 && "sm:grid-cols-2")}>
      {tiles.map((tile, index) => {
        const on = chosen === tile.answer;
        return (
          <div key={tile.answer}
            className={cn("flex min-w-0 flex-col rounded-2xl border bg-card shadow-soft transition-colors has-[button[role=radio]:focus-visible]:outline-2 has-[button[role=radio]:focus-visible]:outline-offset-2 has-[button[role=radio]:focus-visible]:outline-ring",
              on ? "border-primary ring-2 ring-primary/30" : "hover:border-primary/50")}>
            <button ref={(node) => { refs.current[index] = node; }} type="button" role="radio" aria-checked={on}
              tabIndex={index === focus ? 0 : -1} disabled={busy} onKeyDown={(e) => move(e, index)}
              onFocus={() => setFocus(index)} onClick={() => onChoose(tile.answer)}
              aria-label={tile.value ? fill(text.conflictTileAria, { tile: tile.title, value: tile.value }) : tile.title}
              className="flex min-h-24 flex-1 flex-col items-start gap-1 rounded-2xl px-4 pb-2 pt-4 text-left focus-visible:outline-none disabled:opacity-60">
              {/* A tile without a value (a file's owner) is its answer, in large type. */}
              {tile.value ? (
                <>
                  <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">{tile.title}</span>
                  <span className="break-words text-xl font-semibold leading-snug">{tile.value}</span>
                </>
              ) : <span className="my-auto break-words text-xl font-semibold leading-snug">{tile.title}</span>}
            </button>
            {tile.source && <div className="px-4 pb-4"><SourceLine source={tile.source} openDocument={openDocument} /></div>}
          </div>
        );
      })}
    </div>
  );
}

/** The short line after an answer, read out by screen readers. */
function successLine(card: VaultConflict, outcome: Outcome, type: VaultCatalogType | null, filename: string) {
  if (card.kind === "document_owner")
    return fill(outcome.answer === "accept_proposed" ? text.conflictDoneOwnerYes : text.conflictDoneOwnerNo, { filename });
  const label = type?.label || text.conflictLabelFallback;
  switch (outcome.answer) {
    case "keep_current": return fill(text.conflictDoneKept, { value: card.current_display });
    case "both_true": return fill(text.conflictDoneBoth, { old: card.current_display });
    case "provide_new": return fill(text.conflictDoneAccepted, { label, value: human(withChoiceLabels(outcome.value, type)) });
    default: return fill(text.conflictDoneAccepted, { label, value: card.proposed_display });
  }
}

/** One conflict: the tiles, the other answers, and the success line once answered. */
function ConflictStep({ card, type, outcome, openDocument, headingId, onAnswered }: {
  card: VaultConflict; type: VaultCatalogType | null; outcome: Outcome | undefined; openDocument: OpenDocument;
  headingId: string; onAnswered: (outcome: Outcome) => void;
}) {
  const [busy, setBusy] = useState(false),
    [chosen, setChosen] = useState<VaultAnswer | null>(null),
    [error, setError] = useState<string | null>(null),
    [writing, setWriting] = useState(false),
    [value, setValue] = useState<unknown>(card.proposed ?? card.current ?? "");
  const owner = card.kind === "document_owner";
  const filename = card.proposed_source?.document?.filename || text.conflictOwnerFallback;
  async function resolve(answer: VaultAnswer, next?: unknown) {
    setBusy(true); setChosen(answer); setError(null);
    try {
      await workspaceApi.resolveVaultConflict(card.id, answer, next);
      onAnswered({ answer, value: next });
    } catch (failure) {
      setError(vaultError(failure) || text.checkFailed);
      setChosen(null);
    } finally {
      setBusy(false);
    }
  }
  if (outcome)
    return (
      <div role="status" aria-live="polite"
        className="flex items-start gap-3 rounded-2xl border border-success/30 bg-success-soft p-5 text-success-ink motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95">
        <CircleCheck aria-hidden className="mt-0.5 size-6 shrink-0" />
        <p className="break-words text-base font-semibold">{successLine(card, outcome, type, filename)}</p>
      </div>
    );
  const offers = (answer: VaultAnswer) => card.answers.includes(answer);
  const tiles: Tile[] = owner
    ? [
        { answer: "accept_proposed" as const, title: text.conflictOwnerYes, value: "", source: null },
        { answer: "keep_current" as const, title: text.conflictOwnerNo, value: "", source: null },
      ].filter((tile) => offers(tile.answer))
    : [
        { answer: "keep_current" as const, title: text.conflictSavedTile, value: card.current_display, source: card.current_source },
        { answer: "accept_proposed" as const, title: text.conflictNewTile, value: card.proposed_display, source: card.proposed_source },
      ].filter((tile) => offers(tile.answer));
  return (
    <div className="space-y-4">
      {owner && (
        <div className="space-y-1.5 rounded-2xl bg-muted/60 px-4 py-3 text-sm">
          {card.proposed_source?.document && openDocument ? (
            <button type="button" onClick={() => openDocument(card.proposed_source!.document!.file_id)}
              className="flex items-center gap-1.5 font-semibold text-primary hover:underline">
              <FileText aria-hidden className="size-4 shrink-0" /><span className="break-all">{fill(text.openDocument, { filename })}</span>
            </button>
          ) : <p className="flex items-center gap-1.5 font-semibold"><FileText aria-hidden className="size-4 shrink-0" /><span className="break-all">{filename}</span></p>}
          {card.proposed_display && <p className="break-words">{fill(text.conflictOwnerName, { name: card.proposed_display })}</p>}
          {card.current_display && <p className="break-words text-muted-foreground">{fill(text.conflictOwnerVault, { name: card.current_display })}</p>}
        </div>
      )}
      {!writing && <Tiles tiles={tiles} labelledBy={headingId} busy={busy} chosen={chosen} onChoose={(answer) => void resolve(answer)} openDocument={openDocument} />}
      {writing ? (
        <div className="space-y-3 rounded-2xl border bg-card p-4 shadow-soft">
          <ValueEditor value={value} onChange={setValue} label={text.checkNewLabel} choices={type?.choices} />
          <div className="flex flex-wrap gap-2">
            <Button size="tap" disabled={busy || !human(value)} onClick={() => void resolve("provide_new", value)}>{copy.save}</Button>
            <Button size="tap" variant="ghost" onClick={() => setWriting(false)}>{copy.cancel}</Button>
          </div>
        </div>
      ) : (offers("both_true") || offers("provide_new")) && (
        <div className="flex flex-col items-start gap-1">
          {offers("both_true") && (
            <Button size="tap" variant="ghost" disabled={busy} onClick={() => void resolve("both_true")}
              className="-ms-3 h-auto flex-col items-start gap-0 whitespace-normal py-2 text-left">
              <span className="inline-flex items-center gap-2"><History aria-hidden className="size-4" />{text.checkBoth}</span>
              <span className="ps-6 text-xs font-normal text-muted-foreground">{text.conflictBothHint}</span>
            </Button>
          )}
          {offers("provide_new") && (
            <Button size="tap" variant="ghost" disabled={busy} onClick={() => setWriting(true)} className="-ms-3 whitespace-normal text-left">
              <PencilLine aria-hidden className="size-4" />{text.checkNew}
            </Button>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-sm font-medium text-danger-ink">{error}</p>}
    </div>
  );
}

const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** The walk through the open conflicts, one at a time. The list is fixed
 * when the dialog opens, so answering never reshuffles what is left. */
function ReviewFlow({ conflicts, startId, typeOf, openDocument, onAnswered, onClose }: {
  conflicts: VaultConflict[]; startId: string | null; typeOf: (key: string) => VaultCatalogType | null;
  openDocument: OpenDocument; onAnswered: () => void; onClose: () => void;
}) {
  const [queue] = useState(conflicts);
  const [index, setIndex] = useState(() => Math.max(0, queue.findIndex((c) => c.id === startId)));
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [finished, setFinished] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const card = queue[index];
  const outcome = card ? outcomes[card.id] : undefined;
  const next = () => (index + 1 < queue.length ? setIndex(index + 1) : setFinished(true));
  useEffect(() => { if (index > 0 || finished) heading.current?.focus(); }, [index, finished]);
  useEffect(() => {
    if (!outcome || finished || reducedMotion()) return;
    const timer = window.setTimeout(next, ADVANCE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outcome, index, finished]);

  if (finished || !card) {
    const left = queue.filter((c) => !outcomes[c.id]).length;
    return (
      <>
        <DialogHeader className="pe-14 text-start">
          <DialogTitle ref={heading} tabIndex={-1} className="text-xl font-bold leading-tight outline-none">
            {left ? text.conflictSomeLeft : text.conflictAllDone}
          </DialogTitle>
          <DialogDescription className="sr-only">{text.conflictDialogTitle}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div role="status" aria-live="polite" className="flex items-start gap-3 rounded-2xl border border-success/30 bg-success-soft p-5 text-success-ink">
            <CircleCheck aria-hidden className="mt-0.5 size-6 shrink-0" />
            <p className="text-base font-semibold">
              {left ? (left === 1 ? text.conflictLeftOne : fill(text.conflictLeftMany, { count: left })) : text.conflictAllDone}
            </p>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button size="tap" onClick={onClose}>{text.conflictClose}</Button>
        </DialogFooter>
      </>
    );
  }
  const n = index + 1, total = queue.length;
  return (
    <>
      <DialogHeader className="space-y-3 pe-14 text-start">
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold tabular-nums text-muted-foreground">{fill(text.conflictProgress, { n, total })}</span>
          <div role="progressbar" aria-label={fill(text.conflictProgressLabel, { n, total })} aria-valuemin={1} aria-valuemax={total} aria-valuenow={n}
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${(n / total) * 100}%` }} />
          </div>
        </div>
        {/* The question names the radio group; the title keeps Radix's own id. */}
        <DialogTitle ref={heading} tabIndex={-1} className="break-words text-xl font-bold leading-tight outline-none">
          <span id={`conflict-q-${card.id}`}>{card.question}</span>
        </DialogTitle>
        <DialogDescription className="sr-only">{text.conflictDialogTitle}</DialogDescription>
      </DialogHeader>
      <DialogBody className="pb-2">
        <ConflictStep key={card.id} card={card} type={card.type ? typeOf(card.type) : null} outcome={outcome}
          headingId={`conflict-q-${card.id}`} openDocument={openDocument}
          onAnswered={(result) => { setOutcomes((all) => ({ ...all, [card.id]: result })); onAnswered(); }} />
      </DialogBody>
      <DialogFooter className="sm:space-x-0 sm:gap-2">
        {outcome
          ? <Button size="tap" onClick={next}>{text.conflictNext}<ArrowRight aria-hidden /></Button>
          : <Button size="tap" variant="ghost" onClick={next}>{text.conflictSkip}</Button>}
      </DialogFooter>
    </>
  );
}

/** The review dialog: centred on wide screens, a full-height sheet on phones. */
export function ConflictReview({ conflicts, startId, open, typeOf, openDocument, onAnswered, onClose }: {
  conflicts: VaultConflict[]; startId: string | null; open: boolean; typeOf: (key: string) => VaultCatalogType | null;
  openDocument: OpenDocument; onAnswered: () => void; onClose: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        className="max-w-2xl max-sm:inset-0 max-sm:left-0 max-sm:top-0 max-sm:h-dvh max-sm:max-h-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none max-sm:border-0">
        {open && (
          <ReviewFlow conflicts={conflicts} startId={startId} typeOf={typeOf} onAnswered={onAnswered} onClose={onClose}
            openDocument={openDocument && ((fileId) => { onClose(); openDocument(fileId); })} />
        )}
      </DialogContent>
    </Dialog>
  );
}
