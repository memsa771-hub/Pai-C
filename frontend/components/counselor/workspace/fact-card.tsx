"use client";
import { useRef, useState } from "react";
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
  return (
    <section
      className="my-4 max-w-lg rounded-2xl border border-primary/20 bg-primary/5 p-5"
      aria-label={card.label}
    >
      <h3 className="font-semibold">{card.label}</h3>
      {saved ? (
        <p role="status" className="mt-3 text-primary">
          {copy.saved}
        </p>
      ) : (
        <>
          {card.prefill && (
            <blockquote className="my-3 border-l-2 pl-3 text-sm text-muted-foreground">
              {copy.quote}: “{card.prefill.quote}”
            </blockquote>
          )}
          {card.choices.length > 0 && (
            <div className="my-3 flex flex-wrap gap-2">
              {card.choices.map((choice) => (
                <Button
                  variant={
                    value === choice.value && !other ? "primary" : "outline"
                  }
                  key={choice.value}
                  aria-pressed={value === choice.value && !other}
                  onClick={() => {
                    setOther(false);
                    edit(choice.value);
                  }}
                >
                  {choice.label}
                </Button>
              ))}
              <Button
                variant={other ? "primary" : "outline"}
                aria-pressed={other}
                onClick={() => {
                  setOther(true);
                  edit("");
                }}
              >
                {copy.other}
              </Button>
            </div>
          )}
          {(other || !card.choices.length) && (
            <Input
              className="my-3"
              aria-label={card.label}
              value={value}
              onChange={(e) => edit(e.target.value)}
            />
          )}
          {other && (
            <p className="mb-3 text-xs text-muted-foreground">
              {copy.otherHelp}
            </p>
          )}
          {error && (
            <p role="alert" className="my-2 text-sm text-destructive">
              {copy.error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={submit} disabled={busy || !value.trim()}>
              {copy.confirmValue}
            </Button>
            {card.upload_invite && (
              <Button variant="outline" onClick={() => openView("files")}>
                {copy.upload}
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
