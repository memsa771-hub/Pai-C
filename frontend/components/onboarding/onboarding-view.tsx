'use client';

/** Three short steps of schema-driven questions; deeper discovery stays in the
 * conversation. The backend owns which fields exist, their step, choices and
 * defaults; this file owns how they look. */

import * as React from 'react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { AuthField, AuthShell, SubmitButton, authInputClass, type AuthPanel } from '@/components/auth/auth-shell';
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
  // One Figma frame per step: 01 Your name, 02 About you, 03 Your location.
  const panel: AuthPanel = (['name', 'about', 'location'] as const)[Math.min(index, 2)];
  const first = index === 0;
  return (
    <MotionConfig reducedMotion="user">
      <AuthShell panel={panel} prompt={translated(`onboarding.steps.${stepKey}.bubble`, t('onboarding.subtitle'))}
        logoGap={first ? 29 : 31}>
        <form onSubmit={next} noValidate className={cn('flex flex-col', first ? 'gap-[var(--auth-gap)]' : 'gap-[var(--auth-gap-onb)]')}>
          <h1 className={cn('text-center text-[length:var(--auth-title-onb)] font-bold text-auth-ink', first ? 'leading-[1.45]' : 'leading-[1.24]')}>
            {translated(`onboarding.steps.${stepKey}.title`, t('onboarding.title'))}
          </h1>
          <div className="flex flex-col gap-2.5">
            <p className={cn('text-[13px] text-auth-muted', first ? 'leading-[1.45]' : 'leading-[22px]')}>
              {t('onboarding.step', { current: index + 1, total: steps.length })}
            </p>
            <ol className="flex h-1.5 gap-2" aria-label={t('onboarding.step', { current: index + 1, total: steps.length })}>
              {steps.map((s, i) => (
                <li key={s} aria-current={i === index ? 'step' : undefined}
                  className={cn('h-1.5 flex-1 rounded-[3px] transition-colors duration-300',
                    i <= index ? 'bg-auth-blue' : first ? 'bg-auth-track' : 'bg-auth-choice-line')} />
              ))}
            </ol>
          </div>

          <AnimatePresence mode="wait" initial={false} custom={direction}>
            <motion.div key={step} custom={direction}
              initial={{ opacity: 0, x: direction * 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: direction * -24 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className={cn('grid', first ? 'grid-cols-2 gap-4' : 'gap-[var(--auth-gap-onb)]')}>
              {fields.map((field) => (
                <Field key={field.name} field={field} value={answers[field.name] || ''} error={errors[field.name]} size={first ? 'sm' : 'md'}
                  label={translated(`onboarding.field.${field.name}`, field.name)}
                  placeholder={translated(`onboarding.placeholder.${field.name}`, '')}
                  onChange={(v) => set(field.name, v)} />
              ))}
            </motion.div>
          </AnimatePresence>

          <div className="flex items-start gap-3.5">
            {!first && (
              <button type="button" onClick={back} disabled={busy}
                className="flex h-[var(--auth-control)] w-24 shrink-0 items-center justify-center gap-2 text-[17px] leading-[22px] text-auth-back">
                <img alt="" src="/auth/back.svg" className="size-[18px]" />{t('onboarding.back')}
              </button>
            )}
            <SubmitButton busy={busy} busyLabel={t('onboarding.continue')}>
              {last ? t('onboarding.continue') : t('onboarding.next')}
            </SubmitButton>
          </div>
          <p className="text-center text-[13px] leading-[21px] text-auth-muted">{t('onboarding.privacy')}</p>
        </form>
      </AuthShell>
    </MotionConfig>
  );
}

function Field({ field, label, placeholder, value, error, size, onChange }: {
  field: OnboardingFieldSpec;
  label: string;
  placeholder: string;
  value: string;
  error?: boolean;
  size: 'sm' | 'md';
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
  // "PAI / Onboarding / Choice": 42px tall, 16px corners, sized to its label.
  const chip = (on: boolean) => cn(
    'flex h-[42px] items-center justify-center whitespace-nowrap rounded-[16px] border px-4 text-[16px] leading-[22px] transition-colors',
    on ? 'border-auth-blue bg-auth-panel text-auth-blue' : 'border-auth-choice-line bg-white text-auth-choice-ink',
  );
  const errorText = error ? t('onboarding.required') : null;

  if (field.choices.length > 0) {
    return (
      <div className="flex flex-col gap-2.5">
        <span id={`${id}-label`} className="text-[15px] font-bold leading-[22px] text-auth-label">{label}</span>
        <div role="group" aria-labelledby={`${id}-label`} aria-describedby={error ? `${id}-error` : undefined} className="flex flex-col gap-2.5">
          <div className="flex flex-wrap gap-2.5">
            {field.choices.map((choice, i) => (
              <button key={choice} data-field={i === 0 ? field.name : undefined} type="button" aria-pressed={value === choice && !other}
                className={chip(value === choice && !other)} onClick={() => { setOther(false); onChange(choice); }}>
                {choiceLabel(choice)}
              </button>
            ))}
          </div>
          {field.allowOther && (
            <div className="flex">
              <button type="button" aria-pressed={other} className={chip(other)} onClick={() => { setOther(true); onChange(''); }}>
                {choiceLabel('other')}
              </button>
            </div>
          )}
        </div>
        {other && (
          <Input aria-labelledby={`${id}-label`} autoFocus value={value} placeholder={t('onboarding.otherPlaceholder')}
            className={authInputClass} onChange={(event) => onChange(event.target.value)} />
        )}
        {errorText && <p id={`${id}-error`} className="text-xs font-medium text-danger-ink">{errorText}</p>}
      </div>
    );
  }

  return (
    <AuthField label={label} error={errorText} size={size}
      hint={field.options && field.options.length === 1 ? t('onboarding.countryNote') : undefined}>
      {(props) => field.isDate ? (
        <DobPicker id={props.id} field={field.name} value={value} onChange={onChange} invalid={!!error} describedBy={props['aria-describedby']} />
      ) : field.options && field.options.length > 0 ? (
        <div className="relative">
          <select {...props} data-field={field.name} value={value} onChange={(e) => onChange(e.target.value)}
            className={cn(authInputClass, 'appearance-none pe-10 outline-none')}>
            {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
          <img alt="" src="/auth/chevron.svg" className="pointer-events-none absolute end-4 top-1/2 size-4 -translate-y-1/2" />
        </div>
      ) : (
        <Input {...props} data-field={field.name} value={value} placeholder={placeholder || undefined}
          autoComplete={field.name === 'firstName' ? 'given-name' : field.name === 'lastName' ? 'family-name' : field.name === 'currentCity' ? 'address-level2' : undefined}
          className={authInputClass} onChange={(e) => onChange(e.target.value)} />
      )}
    </AuthField>
  );
}
