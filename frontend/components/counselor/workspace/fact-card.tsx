"use client";
import { useRef, useState } from "react";
import { Check, ClipboardCheck, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { workspaceApi } from "@/lib/api";
import { useLayout } from "@/components/layout/layout-context";
import copy from "./copy.json";
export type OfferedFact = {
  key: string;
  label: string;
  kind: string;
  choices: { value: string; label: string }[];
  upload_invite?: string | null;
  record_id?: string | null;
  education_id?: string | null;
  prefill?: { value: string; quote: string };
};
export function FactCard({ card }: { card: OfferedFact }) {
  const [value, setValue] = useState(card.prefill?.value || ""),
    [other, setOther] = useState(false),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false),
    [error, setError] = useState(false);
  const id = useRef(crypto.randomUUID());
  const { openView } = useLayout();
  const edit = (text: string) => {
    setValue(text);
    id.current = crypto.randomUUID();
    setError(false);
  };
  async function submit() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.answerFactCard(card.key, {
        submission_id: id.current,
        value,
        other,
        confirmed: true,
        record_id: card.record_id || null,
        education_id: card.education_id || null,
      });
      setSaved(true);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  const chip = (selected: boolean) => cn(
    "min-h-11 rounded-2xl border-2 px-4 text-sm font-semibold transition-colors",
    selected ? "border-brand bg-brand-soft text-brand-ink" : "border-border bg-card hover:border-brand/40",
  );
  return (
    <section
      className="my-3 max-w-lg rounded-2xl border bg-card p-4 shadow-soft sm:p-5"
      aria-label={card.label}
    >
      <div className="flex items-center gap-2.5">
        <span aria-hidden className="flex size-9 items-center justify-center rounded-xl bg-tone-teal-soft text-tone-teal-ink"><ClipboardCheck className="size-[18px]" /></span>
        <h3 className="font-bold">{card.label}</h3>
      </div>
      {saved ? (
        <p role="status" className="mt-3 flex items-center gap-2 font-medium text-success-ink">
          <Check aria-hidden className="size-4" />{copy.saved}
        </p>
      ) : (
        <>
          {card.prefill && (
            <blockquote className="mt-3 rounded-xl border-l-4 border-tone-teal bg-muted/60 px-3 py-2 text-sm">
              <span className="block text-xs font-semibold text-muted-foreground">{copy.quote}</span>“{card.prefill.quote}”
            </blockquote>
          )}
          {card.choices.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {card.choices.map((choice) => (
                <button
                  type="button"
                  className={chip(value === choice.value && !other)}
                  key={choice.value}
                  aria-pressed={value === choice.value && !other}
                  onClick={() => {
                    setOther(false);
                    edit(choice.value);
                  }}
                >
                  {choice.label}
                </button>
              ))}
              <button
                type="button"
                className={chip(other)}
                aria-pressed={other}
                onClick={() => {
                  setOther(true);
                  edit("");
                }}
              >
                {copy.other}
              </button>
            </div>
          )}
          {(other || !card.choices.length) && (
            <Input
              className="mt-3 h-11 rounded-xl"
              aria-label={card.label}
              value={value}
              onChange={(e) => edit(e.target.value)}
            />
          )}
          {other && (
            <p className="mt-2 text-xs text-muted-foreground">
              {copy.otherHelp}
            </p>
          )}
          {error && (
            <p role="alert" className="mt-2 text-sm font-medium text-danger-ink">
              {copy.error}
            </p>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="tap" onClick={submit} disabled={busy || !value.trim()}>
              {copy.confirmValue}
            </Button>
            {card.upload_invite && (
              <Button size="tap" variant="soft" onClick={() => openView("files")}>
                <Upload aria-hidden />{copy.upload}
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
