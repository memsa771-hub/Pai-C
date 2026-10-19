'use client';

/** Four schema-driven entry cards; deeper discovery stays in the conversation. */

import * as React from 'react';
import Image from 'next/image';
import { ArrowRight, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { workspaceApi } from '@/lib/api';
import { useT, type MessageKey } from '@/lib/i18n';
import {
  FIELD_LAYOUT, visibleOnboardingAnswers,
  type OnboardingAnswers, type OnboardingFieldSpec, type OnboardingState,
} from '@/lib/onboarding';

/** Pull the human message out of an API error like `API 400: {json}`. */
function errorMessage(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  const brace = raw.indexOf('{');
  if (brace >= 0) {
    try {
      const parsed = JSON.parse(raw.slice(brace));
      if (parsed && typeof parsed.message === 'string') return parsed.message;
    } catch { /* not JSON */ }
  }
  return raw.startsWith('API ') ? '' : raw;
}

export function OnboardingView({ state, onDone }: {
  state: OnboardingState;
  onDone: () => void;
}) {
  const t = useT();
  const [answers, setAnswers] = React.useState<OnboardingAnswers>(state.prefill || {});
  const [busy, setBusy] = React.useState(false);

  const set = (name: string, value: string) =>
    setAnswers((prev) => ({ ...prev, [name]: value }));

  const label = (name: string) => {
    const key = `onboarding.field.${name}`;
    const text = t(key as MessageKey);
    return text === key ? name : text;
  };

  const missingRequired = state.fields.some(
    (f) => f.required && !(answers[f.name] || '').trim(),
  );

  const submit = async () => {
    setBusy(true);
    try {
      // The prefill may contain legacy fields absent from the four visible
      // cards. Submit only answers the student had an opportunity to review.
      const result = await workspaceApi.submitOnboarding(visibleOnboardingAnswers(state.fields, answers));
      // The backend reports per-field rejections rather than failing the whole
      // call. Saying "saved" over a rejected field would be a lie about
      // canonical state, so surface it.
      const rejected = Object.keys(result.rejected || {});
      if (rejected.length || !result.completed) {
        toast.warning(t('onboarding.partial', { count: rejected.length }));
        setBusy(false);
      } else {
        toast.success(t('onboarding.saved'));
        onDone();
      }
    } catch (e) {
      toast.error(errorMessage(e) || t('onboarding.failed'));
      setBusy(false);
    }
  };

  return (
    /* `w-full` matters: LayoutProvider wraps children in `flex grow`, so
       without it this sizes to its content and the body background
       shows through beside the form. */
    <div className="h-svh w-full overflow-y-auto bg-background">
      <div className="mx-auto w-full max-w-lg px-5 py-10 sm:py-14">
        <div className="flex flex-col items-center text-center">
          <Image
            src="/pai-emblem.png"
            alt="Placement AI"
            width={40}
            height={40}
            className="size-10 object-contain"
          />
          <h1 className="mt-4 text-xl font-semibold tracking-tight sm:text-2xl">
            {t('onboarding.title')}
          </h1>
          <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">
            {t('onboarding.subtitle')}
          </p>
        </div>

        <div className="mt-8 grid grid-cols-2 gap-3">
          {state.fields.map((field) => (
            <Field
              key={field.name}
              field={field}
              label={label(field.name)}
              value={answers[field.name] || ''}
              onChange={(v) => set(field.name, v)}
            />
          ))}
        </div>

        <p className="mt-4 text-xs text-muted-foreground">{t('onboarding.privacy')}</p>

        <div className="mt-6 flex items-center gap-2">
          <Button
            className="flex-1"
            onClick={submit}
            disabled={busy || missingRequired}
          >
            {busy
              ? <Loader2 className="size-4 animate-spin" />
              : <>{t('onboarding.continue')}<ArrowRight className="size-4" /></>}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Field({ field, label, value, onChange }: {
  field: OnboardingFieldSpec;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useT();
  // A field the backend added but the layout map has not caught up with still
  // renders — full width, plain text box — rather than silently vanishing.
  const layout = FIELD_LAYOUT[field.name] || {};
  // Explicitly tied to the control: tapping the label focuses it, and a screen
  // reader announces the two together instead of reading an unlabelled box.
  const id = React.useId();
  const [other, setOther] = React.useState(!!value && !!field.allowOther && !field.choices.includes(value));
  const choiceLabel = (choice: string) => {
    const key = `onboarding.choice.${choice}`;
    const translated = t(key as MessageKey);
    return translated === key ? choice : translated;
  };

  return (
    <div className="col-span-2 space-y-3 rounded-xl border bg-card p-5 shadow-sm">
      <Label htmlFor={id} className="text-xs">
        {label}
        {field.required && <span className="ms-1 text-destructive">*</span>}
      </Label>

      {field.choices.length > 0 ? (
        <div role="group" aria-label={label} className="flex flex-wrap gap-2">
          {field.choices.map(choice => <Button key={choice} type="button" variant={value === choice ? 'primary' : 'outline'} aria-pressed={value === choice} onClick={() => {setOther(false);onChange(choice);}}>
            {choiceLabel(choice)}
          </Button>)}
          {field.allowOther && <Button type="button" variant={other?'primary':'outline'} aria-pressed={other} onClick={()=>{setOther(true);onChange('');}}>{choiceLabel('other')}</Button>}
          {other && <Input id={id} aria-label={label} value={value} onChange={event=>onChange(event.target.value)}/>}
        </div>
      ) : field.isDate ? (
        <Input
          id={id}
          type="date"
          value={value}
          max={new Date().toISOString().slice(0, 10)}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <Input
          id={id}
          value={value}
          placeholder={layout.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
