'use client';

import { useId, useState } from 'react';
import Link from 'next/link';
import type { LucideIcon } from 'lucide-react';
import { AlertCircle, ArrowUp, ChevronDown, Compass, Eye, EyeOff, Loader2, Mic, Plus } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { useT } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/** Decorative preview of talking with PAI, under the mascot. Not interactive. */
function PromptPreview() {
  const t = useT();
  return (
    <div aria-hidden className="w-full max-w-[505px] rounded-2xl bg-auth-card p-3 shadow-[0_1px_2px_rgb(0_0_0/0.06),0_12px_32px_-12px_rgb(0_0_0/0.18)]">
      <p className="px-1.5 pt-1 text-[15px] leading-relaxed text-auth-ink">
        {t('auth.previewPrompt')}<span className="ms-0.5 inline-block h-4 w-px translate-y-0.5 bg-brand" />
      </p>
      <div className="mt-3 flex items-center gap-2">
        <span className="flex size-9 items-center justify-center rounded-lg border border-auth-line text-auth-ink"><Plus className="size-4" /></span>
        <span className="flex h-9 items-center gap-1.5 rounded-lg border border-auth-line px-3 text-sm text-auth-muted">
          <Compass className="size-4 text-success" />{t('auth.previewChip')}<ChevronDown className="size-3.5" />
        </span>
        <span className="ms-auto flex h-9 items-center gap-1.5 rounded-lg bg-auth-page px-3 text-sm font-medium text-auth-ink">
          {t('auth.previewModel')}<ChevronDown className="size-3.5" />
        </span>
        <span className="flex size-9 items-center justify-center text-auth-muted"><Mic className="size-4" /></span>
        <span className="flex size-10 items-center justify-center rounded-[10px] bg-gradient-to-b from-[var(--auth-button-from)] to-[var(--auth-button-to)] text-auth-button-ink">
          <ArrowUp className="size-4" />
        </span>
      </div>
    </div>
  );
}

/** PAI speaking in the showcase: a white bubble with the PAI mark. */
export function SpeechBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full max-w-[505px] items-start gap-3 rounded-2xl bg-auth-card p-4 shadow-[0_1px_2px_rgb(0_0_0/0.06),0_12px_32px_-12px_rgb(0_0_0/0.18)]">
      <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white ring-1 ring-auth-line">
        <img src="/pai-emblem.png" alt="" className="size-6 object-contain" />
      </span>
      <p aria-live="polite" className="pt-0.5 text-[15px] font-medium leading-relaxed text-auth-ink">{children}</p>
    </div>
  );
}

/** One auth layout that fits the screen: the form on the left with the PAI
 * logo, and a full-height showcase with the mascot on the right. Desktop never
 * scrolls; very short screens scroll only the form column. Phones show the form. */
export function AuthShell({ title, children, footer, showcase }: {
  title?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** What sits under the mascot; the chat preview by default. */
  showcase?: React.ReactNode;
}) {
  const t = useT();
  return (
    <div className="grid min-h-svh w-full bg-auth-card lg:h-svh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-4 lg:overflow-hidden lg:p-4">
      <main className="flex items-center justify-center px-6 py-10 sm:px-10 lg:overflow-y-auto lg:py-6 [@media(max-height:680px)]:lg:py-1">
        <div className="w-full max-w-[400px]">
          <img src="/pai-emblem.png" alt="Placement AI" width={56} height={56}
            className="mx-auto mb-5 size-14 object-contain dark:rounded-2xl dark:bg-white dark:p-2 [@media(max-height:780px)]:mb-3 [@media(max-height:780px)]:size-11 [@media(max-height:680px)]:mb-2 [@media(max-height:680px)]:size-9" />
          {title && <h1 className="mb-8 text-center text-[32px] font-bold leading-tight tracking-tight text-auth-ink [@media(max-height:780px)]:mb-5 [@media(max-height:780px)]:text-[28px] [@media(max-height:680px)]:mb-4 [@media(max-height:680px)]:text-[26px]">{title}</h1>}
          {children}
          {footer && <div className="mt-6 text-center text-sm font-medium text-auth-ink [@media(max-height:780px)]:mt-4 [@media(max-height:680px)]:mt-2">{footer}</div>}
        </div>
      </main>
      <aside aria-label={t('auth.previewLabel')}
        className="relative hidden flex-col items-center justify-end overflow-hidden rounded-[28px] bg-auth-panel px-8 pb-6 lg:flex">
          <img src="/pai-mascot.webp" alt={t('auth.mascotAlt')} width={702} height={855}
            className="absolute left-1/2 top-[8%] h-[60%] w-auto -translate-x-1/2 object-contain drop-shadow-[0_24px_30px_rgb(0_0_0/0.12)]" />
          {showcase ?? <PromptPreview />}
        </aside>
    </div>
  );
}

/** Label + control + optional hint/error, wired for screen readers. */
export function AuthField({ label, hint, error, children }: {
  label: string;
  hint?: string;
  error?: string | null;
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => React.ReactNode;
}) {
  const id = useId();
  const described = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold text-auth-ink">{label}</label>
      {children({ id, 'aria-describedby': described, 'aria-invalid': error ? true : undefined })}
      {error ? <p id={`${id}-error`} className="flex items-center gap-1.5 text-xs font-medium text-danger-ink"><AlertCircle aria-hidden className="size-3.5" />{error}</p>
        : hint ? <p id={`${id}-hint`} className="text-[11px] leading-snug text-auth-muted">{hint}</p> : null}
    </div>
  );
}

export const isEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

export const authInputClass = 'h-12 rounded-xl border-auth-line bg-auth-field px-4 text-[15px] font-medium text-auth-ink shadow-[inset_0_1px_2px_rgb(0_0_0/0.04)] placeholder:font-normal placeholder:text-auth-muted/80 [@media(max-height:780px)]:h-11 [@media(max-height:680px)]:h-10!';

export function PasswordInput({ className, ...props }: React.ComponentProps<typeof Input>) {
  const t = useT();
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? 'text' : 'password'} className={cn(authInputClass, 'pe-12', className)} />
      <button type="button" onClick={() => setVisible(!visible)} aria-pressed={visible} aria-label={t('auth.showPassword')}
        className="absolute inset-y-0 end-0 flex w-12 items-center justify-center rounded-e-xl text-auth-muted hover:text-auth-ink">
        {visible ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
      </button>
    </div>
  );
}

export function AuthAlert({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-xs font-medium text-danger-ink">
      <AlertCircle aria-hidden className="mt-px size-4 shrink-0" />{children}
    </p>
  );
}

const inkButton = 'flex h-12 w-full items-center justify-center gap-2 rounded-xl [@media(max-height:780px)]:h-11 [@media(max-height:680px)]:h-10! bg-gradient-to-b from-[var(--auth-button-from)] to-[var(--auth-button-to)] text-[15px] font-semibold text-auth-button-ink shadow-[0_1px_2px_rgb(0_0_0/0.2),inset_0_1px_0_rgb(255_255_255/0.12)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50';

/** Always pressable (as in the design); forms validate on submit and say
 * exactly what is missing, instead of a silently disabled button. */
export function SubmitButton({ busy, busyLabel, children }: {
  busy: boolean; busyLabel: string; children: React.ReactNode;
}) {
  return (
    <button type="submit" className={inkButton} disabled={busy} aria-busy={busy}>
      {busy ? <><Loader2 aria-hidden className="size-4 animate-spin" />{busyLabel}</> : children}
    </button>
  );
}

/** A link styled like the primary button, for status screens. */
export function InkLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className={inkButton}>{children}</Link>;
}

/** The small grey footer link under each form. */
export function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="inline-flex min-h-11 items-center font-bold text-auth-ink underline underline-offset-4 hover:opacity-80">{children}</Link>;
}

/** Google's multicolour "G", as Google's sign-in guidelines require. */
function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 48 48" className="size-[18px]">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export function GoogleButton({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-auth-line bg-gradient-to-b from-[var(--auth-google-from)] to-[var(--auth-google-to)] text-[15px] font-semibold text-auth-ink [@media(max-height:780px)]:h-11 [@media(max-height:680px)]:h-10! shadow-[0_1px_2px_rgb(0_0_0/0.08),inset_0_1px_0_rgb(255_255_255/0.7)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50">
      <GoogleMark />{label}
    </button>
  );
}

export function OrDivider() {
  const t = useT();
  return (
    <div className="my-6 flex items-center gap-4 text-xs font-semibold uppercase tracking-wider text-auth-muted [@media(max-height:780px)]:my-4 [@media(max-height:680px)]:my-3">
      <span aria-hidden className="h-px flex-1 bg-auth-line" />{t('auth.or')}<span aria-hidden className="h-px flex-1 bg-auth-line" />
    </div>
  );
}

/** A finished or blocked step: an icon, a message, and one way forward. */
export function AuthStatus({ icon: Icon, tone = 'neutral', title, body, children }: {
  icon: LucideIcon; tone?: 'neutral' | 'success' | 'warning'; title: string; body?: string; children?: React.ReactNode;
}) {
  return (
    <div role="status" className="text-center">
      <span aria-hidden className={cn('mx-auto mb-5 flex size-14 items-center justify-center rounded-2xl',
        tone === 'neutral' && 'bg-auth-page text-auth-ink', tone === 'success' && 'bg-success-soft text-success-ink',
        tone === 'warning' && 'bg-warning-soft text-warning-ink')}>
        <Icon className="size-7" />
      </span>
      <h1 className="text-[28px] font-bold leading-tight tracking-tight text-auth-ink">{title}</h1>
      {body && <p className="mt-3 text-pretty text-sm text-auth-muted">{body}</p>}
      {children && <div className="mt-7 grid gap-3">{children}</div>}
    </div>
  );
}
