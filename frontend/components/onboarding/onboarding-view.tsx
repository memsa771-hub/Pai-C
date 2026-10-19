'use client';

/** Four schema-driven entry cards, one per step; deeper discovery stays in
 * the conversation. The backend owns which fields exist and their choices. */

import * as React from 'react';
import Image from 'next/image';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { ArrowLeft, ArrowRight, Check, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { workspaceApi } from '@/lib/api';
import { useT, type MessageKey } from '@/lib/i18n';
import { cn } from '@/lib/utils';
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
  const [step, setStep] = React.useState(0);
  const [direction, setDirection] = React.useState(1);
  const fields = state.fields;
  const field = fields[step];
  const last = step === fields.length - 1;

  const set = (name: string, value: string) =>
    setAnswers((prev) => ({ ...prev, [name]: value }));
  const translated = (key: string, fallback: string) => {
    const text = t(key as MessageKey);
    return text === key ? fallback : text;
  };
  const value = (f: OnboardingFieldSpec) => (answers[f.name] || '').trim();
  const missingRequired = fields.some((f) => f.required && !value(f));
  const stepReady = !field?.required || !!value(field);

  const submit = async () => {
    setBusy(true);
    try {
      // The prefill may contain legacy fields absent from the four visible
      // cards. Submit only answers the student had an opportunity to review.
      const result = await workspaceApi.submitOnboarding(visibleOnboardingAnswers(fields, answers));
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
  const go = (delta: number) => { setDirection(delta); setStep((s) => Math.min(fields.length - 1, Math.max(0, s + delta))); };
  const next = () => { if (!stepReady) return; if (last) { if (!missingRequired) void submit(); } else go(1); };

  if (!field) return null;
  return (
    <MotionConfig reducedMotion="user">
      <div data-scroll-root className="relative h-svh w-full overflow-y-auto bg-background">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-80 rounded-b-[2.5rem] bg-gradient-to-br from-[var(--hero-from)] via-[var(--hero-via)] to-[var(--hero-to)] sm:h-[22rem]" />
        <div className="relative mx-auto flex min-h-full w-full max-w-lg flex-col px-4 pb-8 pt-8 sm:pt-14">
          <header className="flex flex-col items-center text-center text-white">
            <span className="flex size-14 items-center justify-center rounded-2xl bg-white shadow-lift">
              <Image src="/pai-emblem.png" alt="Placement AI" width={34} height={34} className="size-8 object-contain" />
            </span>
            <h1 className="mt-4 text-balance text-2xl font-bold tracking-tight sm:text-3xl">{t('onboarding.title')}</h1>
            <p className="mt-1.5 max-w-sm text-pretty text-sm text-white/90">{t('onboarding.subtitle')}</p>
          </header>

          <div className="mt-8 rounded-3xl border bg-card p-6 shadow-card sm:p-8">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-brand-ink">
                {t('onboarding.step', { current: step + 1, total: fields.length })}
              </p>
              <ol className="flex items-center gap-1.5" aria-label={t('onboarding.step', { current: step + 1, total: fields.length })}>
                {fields.map((f, i) => (
                  <li key={f.name} aria-current={i === step ? 'step' : undefined}
                    className={cn('h-2 rounded-full transition-all duration-300',
                      i === step ? 'w-6 bg-brand' : i < step ? 'w-2 bg-brand/60' : 'w-2 bg-border')}>
                    <span className="sr-only">{translated(`onboarding.field.${f.name}`, f.name)}</span>
                  </li>
                ))}
              </ol>
            </div>

            <form className="mt-5" onSubmit={(event) => { event.preventDefault(); next(); }}>
              <AnimatePresence mode="wait" initial={false} custom={direction}>
                <motion.div key={field.name} custom={direction}
                  initial={{ opacity: 0, x: direction * 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: direction * -24 }}
                  transition={{ duration: 0.22, ease: 'easeOut' }}>
                  <Step field={field} label={translated(`onboarding.field.${field.name}`, field.name)}
                    help={translated(`onboarding.help.${field.name}`, '')} value={answers[field.name] || ''}
                    onChange={(v) => set(field.name, v)} />
                </motion.div>
              </AnimatePresence>
              {!stepReady && <p className="mt-3 text-xs text-muted-foreground">{t('onboarding.required')}</p>}

              <div className="mt-8 flex items-center gap-3">
                {step > 0 && (
                  <Button type="button" variant="ghost" size="tap" onClick={() => go(-1)} disabled={busy}>
                    <ArrowLeft aria-hidden />{t('onboarding.back')}
                  </Button>
                )}
                <Button type="submit" size="tap" className="ms-auto h-12 min-w-36" disabled={busy || !stepReady || (last && missingRequired)}>
                  {busy ? <Loader2 aria-hidden className="size-4 animate-spin" />
                    : last ? <>{t('onboarding.continue')}<Check aria-hidden /></>
                    : <>{t('onboarding.next')}<ArrowRight aria-hidden /></>}
                </Button>
              </div>
            </form>
          </div>
          <p className="mt-5 text-center text-xs text-muted-foreground">{t('onboarding.privacy')}</p>
        </div>
      </div>
    </MotionConfig>
  );
}

function Step({ field, label, help, value, onChange }: {
  field: OnboardingFieldSpec;
  label: string;
  help: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useT();
  // A field the backend added but the layout map has not caught up with still
  // renders as a plain text box rather than silently vanishing.
  const layout = FIELD_LAYOUT[field.name] || {};
  const id = React.useId();
  const [other, setOther] = React.useState(!!value && !!field.allowOther && !field.choices.includes(value));
  const choiceLabel = (choice: string) => {
    const key = `onboarding.choice.${choice}`;
    const translated = t(key as MessageKey);
    return translated === key ? choice : translated;
  };
  const chip = (selected: boolean) => cn(
    'min-h-12 rounded-2xl border-2 px-5 text-base font-semibold transition-colors',
    selected ? 'border-brand bg-brand-soft text-brand-ink' : 'border-border bg-card hover:border-brand/40 hover:bg-muted',
  );

  return (
    <div>
      <label htmlFor={field.choices.length ? undefined : id} id={`${id}-label`} className="block text-xl font-bold leading-snug">
        {label}
      </label>
      {help && <p className="mt-1 text-sm text-muted-foreground">{help}</p>}
      <div className="mt-5">
        {field.choices.length > 0 ? (
          <div role="group" aria-labelledby={`${id}-label`} className="flex flex-wrap gap-2.5">
            {field.choices.map((choice) => (
              <button key={choice} type="button" aria-pressed={value === choice && !other} className={chip(value === choice && !other)}
                onClick={() => { setOther(false); onChange(choice); }}>
                {choiceLabel(choice)}
              </button>
            ))}
            {field.allowOther && (
              <button type="button" aria-pressed={other} className={chip(other)} onClick={() => { setOther(true); onChange(''); }}>
                {choiceLabel('other')}
              </button>
            )}
            {other && (
              <Input id={id} aria-labelledby={`${id}-label`} autoFocus value={value} placeholder={t('onboarding.otherPlaceholder')}
                className="mt-1 h-12 w-full rounded-xl px-4 text-base" onChange={(event) => onChange(event.target.value)} />
            )}
          </div>
        ) : (
          <Input id={id} autoFocus type={field.isDate ? 'date' : 'text'} value={value} placeholder={layout.placeholder}
            max={field.isDate ? new Date().toISOString().slice(0, 10) : undefined}
            className="h-14 rounded-2xl px-5 text-lg" onChange={(e) => onChange(e.target.value)} />
        )}
      </div>
    </div>
  );
}
