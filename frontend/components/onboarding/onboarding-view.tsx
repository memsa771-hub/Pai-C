'use client';

/** Three short steps of schema-driven questions; deeper discovery stays in the
 * conversation. The backend owns which fields exist, their step, choices and
 * defaults; this file owns how they look. */

import * as React from 'react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { ArrowLeft, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { AuthField, AuthShell, SpeechBubble, SubmitButton, authInputClass } from '@/components/auth/auth-shell';
import { workspaceApi } from '@/lib/api';
import { useT, type MessageKey } from '@/lib/i18n';
import { cn } from '@/lib/utils';
import {
  visibleOnboardingAnswers,
  type OnboardingAnswers, type OnboardingFieldSpec, type OnboardingState,
} from '@/lib/onboarding';
import { DobPicker } from './dob-picker';

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
  const translated = (key: string, fallback: string) => {
    const text = t(key as MessageKey);
    return text === key ? fallback : text;
  };
  const defaults = Object.fromEntries(state.fields.filter((f) => f.default).map((f) => [f.name, f.default as string]));
  const [answers, setAnswers] = React.useState<OnboardingAnswers>({ ...defaults, ...(state.prefill || {}) });
  const [busy, setBusy] = React.useState(false);
  const [errors, setErrors] = React.useState<Record<string, boolean>>({});
  const steps = React.useMemo(() => [...new Set(state.fields.map((f) => f.step || 1))].sort((a, b) => a - b), [state.fields]);
  const [index, setIndex] = React.useState(0);
  const [direction, setDirection] = React.useState(1);
  const step = steps[index];
  const fields = state.fields.filter((f) => (f.step || 1) === step);
  const last = index === steps.length - 1;

  const set = (name: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => ({ ...prev, [name]: false }));
  };
  const filled = (f: OnboardingFieldSpec) => !!(answers[f.name] || '').trim();

  const submit = async () => {
    setBusy(true);
    try {
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

  const next = (event: React.FormEvent) => {
    event.preventDefault();
    const missing = fields.filter((f) => f.required && !filled(f));
    if (missing.length) {
      setErrors(Object.fromEntries(missing.map((f) => [f.name, true])));
      document.querySelector<HTMLElement>(`[data-field="${missing[0].name}"]`)?.focus();
      return;
    }
    if (last) void submit();
    else { setDirection(1); setIndex(index + 1); }
  };
  const back = () => { setDirection(-1); setIndex(index - 1); };

  const stepKey = String(step);
  return (
    <MotionConfig reducedMotion="user">
      <AuthShell title={translated(`onboarding.steps.${stepKey}.title`, t('onboarding.title'))}
        showcase={<SpeechBubble>{translated(`onboarding.steps.${stepKey}.bubble`, t('onboarding.subtitle'))}</SpeechBubble>}
        footer={<span className="text-xs font-normal text-auth-muted">{t('onboarding.privacy')}</span>}>
        <div className="-mt-4 mb-7 [@media(max-height:780px)]:mb-5">
          <div className="flex items-center justify-between text-xs font-semibold text-auth-muted">
            <span>{t('onboarding.step', { current: index + 1, total: steps.length })}</span>
          </div>
          <ol className="mt-2 grid gap-1.5" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
            aria-label={t('onboarding.step', { current: index + 1, total: steps.length })}>
            {steps.map((s, i) => (
              <li key={s} aria-current={i === index ? 'step' : undefined}
                className={cn('h-1.5 rounded-full transition-colors duration-300', i <= index ? 'bg-auth-ink' : 'bg-auth-line')} />
            ))}
          </ol>
        </div>

        <form onSubmit={next} noValidate>
          <AnimatePresence mode="wait" initial={false} custom={direction}>
            <motion.div key={step} custom={direction}
              initial={{ opacity: 0, x: direction * 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: direction * -24 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className={cn('grid gap-4 [@media(max-height:780px)]:gap-3', fields.every((f) => !f.choices.length && !f.isDate && !f.options?.length) && fields.length === 2 && 'sm:grid-cols-2')}>
              {fields.map((field) => (
                <Field key={field.name} field={field} value={answers[field.name] || ''} error={errors[field.name]}
                  label={translated(`onboarding.field.${field.name}`, field.name)}
                  placeholder={translated(`onboarding.placeholder.${field.name}`, '')}
                  onChange={(v) => set(field.name, v)} />
              ))}
            </motion.div>
          </AnimatePresence>

          <div className="mt-7 flex items-center gap-3 [@media(max-height:780px)]:mt-5">
            {index > 0 && (
              <button type="button" onClick={back} disabled={busy}
                className="flex h-12 items-center gap-2 rounded-xl px-4 text-[15px] font-semibold text-auth-ink transition-colors hover:bg-auth-page [@media(max-height:780px)]:h-11">
                <ArrowLeft aria-hidden className="size-4" />{t('onboarding.back')}
              </button>
            )}
            <div className="flex-1">
              <SubmitButton busy={busy} busyLabel={t('onboarding.continue')}>
                {last ? t('onboarding.continue') : t('onboarding.next')}
              </SubmitButton>
            </div>
          </div>
        </form>
      </AuthShell>
    </MotionConfig>
  );
}

function Field({ field, label, placeholder, value, error, onChange }: {
  field: OnboardingFieldSpec;
  label: string;
  placeholder: string;
  value: string;
  error?: boolean;
  onChange: (value: string) => void;
}) {
  const t = useT();
  const [other, setOther] = React.useState(!!value && !!field.allowOther && !field.choices.includes(value));
  const choiceLabel = (choice: string) => {
    const key = `onboarding.choice.${choice}`;
    const translated = t(key as MessageKey);
    return translated === key ? choice : translated;
  };
  const id = `onb-${field.name}`;
  const chip = (on: boolean) => cn(
    'min-h-11 rounded-xl border px-4 text-sm font-semibold transition-colors [@media(max-height:780px)]:min-h-10',
    on ? 'border-auth-ink bg-auth-ink text-auth-card' : 'border-auth-line bg-auth-field text-auth-ink hover:border-auth-muted/60',
  );
  const errorText = error ? t('onboarding.required') : null;

  if (field.choices.length > 0) {
    return (
      <div className="grid gap-1.5">
        <span id={`${id}-label`} className="text-sm font-semibold text-auth-ink">{label}</span>
        <div role="group" aria-labelledby={`${id}-label`} aria-describedby={error ? `${id}-error` : undefined} className="flex flex-wrap gap-2">
          {field.choices.map((choice, i) => (
            <button key={choice} data-field={i === 0 ? field.name : undefined} type="button" aria-pressed={value === choice && !other}
              className={chip(value === choice && !other)} onClick={() => { setOther(false); onChange(choice); }}>
              {choiceLabel(choice)}
            </button>
          ))}
          {field.allowOther && (
            <button type="button" aria-pressed={other} className={chip(other)} onClick={() => { setOther(true); onChange(''); }}>
              {choiceLabel('other')}
            </button>
          )}
        </div>
        {other && (
          <Input aria-labelledby={`${id}-label`} autoFocus value={value} placeholder={t('onboarding.otherPlaceholder')}
            className={cn(authInputClass, 'mt-1')} onChange={(event) => onChange(event.target.value)} />
        )}
        {errorText && <p id={`${id}-error`} className="text-xs font-medium text-danger-ink">{errorText}</p>}
      </div>
    );
  }

  return (
    <AuthField label={label} error={errorText}>
      {(props) => field.isDate ? (
        <DobPicker id={props.id} field={field.name} value={value} onChange={onChange} invalid={!!error} describedBy={props['aria-describedby']} />
      ) : field.options && field.options.length > 0 ? (
        <div className="relative">
          <select {...props} data-field={field.name} value={value} onChange={(e) => onChange(e.target.value)}
            className={cn(authInputClass, 'w-full appearance-none border pe-10 outline-none')}>
            {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
          <ChevronDown aria-hidden className="pointer-events-none absolute end-4 top-1/2 size-4 -translate-y-1/2 text-auth-muted" />
          {field.options.length === 1 && <p className="mt-1.5 text-[11px] text-auth-muted">{t('onboarding.countryNote')}</p>}
        </div>
      ) : (
        <Input {...props} data-field={field.name} value={value} placeholder={placeholder || undefined}
          autoComplete={field.name === 'firstName' ? 'given-name' : field.name === 'lastName' ? 'family-name' : field.name === 'currentCity' ? 'address-level2' : undefined}
          className={authInputClass} onChange={(e) => onChange(e.target.value)} />
      )}
    </AuthField>
  );
}
