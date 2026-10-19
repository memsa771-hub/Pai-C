'use client';

import { useId, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { AlertCircle, Check, Eye, EyeOff, Loader2 } from 'lucide-react';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { OAUTH_PROVIDERS, type OAuthProvider } from '@/lib/auth/oauth-providers';
import { useT } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/** Soft path illustration: stepping stones toward a flag. Decorative only. */
function PathArt({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 320 220" aria-hidden className={className} fill="none">
      <circle cx="58" cy="58" r="30" fill="white" fillOpacity=".08" />
      <circle cx="272" cy="176" r="36" fill="white" fillOpacity=".08" />
      <path d="M24 200 C 90 192, 76 134, 146 122 S 236 92, 252 44" stroke="white" strokeOpacity=".28" strokeWidth="6" strokeLinecap="round" />
      {[[24, 200], [94, 164], [150, 121], [212, 96], [252, 44]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i === 4 ? 11 : 8} fill="white" fillOpacity={0.45 + i * 0.12} />
      ))}
      <path d="M252 44 V 8" stroke="white" strokeWidth="4" strokeLinecap="round" />
      <path d="M254 10 L 284 19 L 254 28 Z" fill="white" />
    </svg>
  );
}

function Logo() {
  return (
    <span className="flex size-12 items-center justify-center rounded-2xl bg-white shadow-lift">
      <Image src="/pai-emblem.png" alt="Placement AI" width={30} height={30} className="size-7 object-contain" />
    </span>
  );
}

/** Two-panel auth page: a warm brand panel and a clean form card. On a
 * phone the brand panel becomes a short gradient band above the form. */
export function AuthShell({ title, subtitle, children, footer }: {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const t = useT();
  return (
    <div className="flex min-h-svh w-full flex-col bg-background lg:flex-row">
      <aside className="relative overflow-hidden bg-gradient-to-br from-[var(--hero-from)] via-[var(--hero-via)] to-[var(--hero-to)] px-6 pb-16 pt-8 text-white lg:flex lg:w-[44%] lg:flex-col lg:justify-between lg:p-12">
        <div className="relative z-10 flex items-center gap-3">
          <Logo />
          <span className="text-lg font-bold tracking-tight">Placement AI</span>
        </div>
        <div className="relative z-10 mt-6 max-w-md lg:mt-0">
          <p className="text-balance text-2xl font-bold leading-tight sm:text-3xl lg:text-4xl">{t('auth.promise')}</p>
          <p className="mt-3 hidden text-pretty text-white/90 lg:block">{t('auth.promiseBody')}</p>
          <ul className="mt-8 hidden space-y-3 lg:block">
            {(['benefit1', 'benefit2', 'benefit3'] as const).map((key) => (
              <li key={key} className="flex items-center gap-3 text-sm font-medium">
                <span className="flex size-6 items-center justify-center rounded-full bg-white/20"><Check aria-hidden className="size-3.5" /></span>
                {t(`auth.${key}`)}
              </li>
            ))}
          </ul>
        </div>
        <PathArt className="pointer-events-none absolute -bottom-6 right-0 w-56 opacity-70 lg:relative lg:bottom-auto lg:mt-10 lg:w-full lg:max-w-sm lg:opacity-100" />
      </aside>
      <main className="relative z-10 -mt-8 flex flex-1 items-start justify-center px-4 pb-10 lg:mt-0 lg:items-center lg:px-10">
        <div className="w-full max-w-md rounded-3xl border bg-card p-6 shadow-card sm:p-8 lg:border-0 lg:bg-transparent lg:shadow-none">
          {title && <header className="mb-6"><h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            {subtitle && <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>}</header>}
          {children}
          {footer && <div className="mt-6 text-center text-sm text-muted-foreground">{footer}</div>}
        </div>
      </main>
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
      <Label htmlFor={id} className="text-sm font-semibold">{label}</Label>
      {children({ id, 'aria-describedby': described, 'aria-invalid': error ? true : undefined })}
      {error ? <p id={`${id}-error`} className="flex items-center gap-1.5 text-xs font-medium text-danger-ink"><AlertCircle aria-hidden className="size-3.5" />{error}</p>
        : hint ? <p id={`${id}-hint`} className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export const authInputClass = 'h-12 rounded-xl px-4 text-base';

export function PasswordInput({ className, ...props }: React.ComponentProps<typeof Input>) {
  const t = useT();
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? 'text' : 'password'} className={cn(authInputClass, 'pe-12', className)} />
      <button type="button" onClick={() => setVisible(!visible)} aria-pressed={visible}
        aria-label={visible ? t('auth.hidePassword') : t('auth.showPassword')}
        className="absolute inset-y-0 end-0 flex w-12 items-center justify-center rounded-e-xl text-muted-foreground hover:text-foreground">
        {visible ? <EyeOff aria-hidden className="size-5" /> : <Eye aria-hidden className="size-5" />}
      </button>
    </div>
  );
}

export function AuthAlert({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-xl bg-danger-soft px-3.5 py-3 text-sm font-medium text-danger-ink">
      <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />{children}
    </p>
  );
}

export function SubmitButton({ busy, busyLabel, children, disabled }: {
  busy: boolean; busyLabel: string; children: React.ReactNode; disabled?: boolean;
}) {
  return (
    <Button type="submit" size="tap" className="h-12 w-full text-base" disabled={busy || disabled} aria-busy={busy}>
      {busy ? <><Loader2 aria-hidden className="size-4 animate-spin" />{busyLabel}</> : children}
    </Button>
  );
}

export function OAuthButtons({ onSelect, disabled }: { onSelect: (provider: OAuthProvider) => void; disabled?: boolean }) {
  const t = useT();
  return (
    <>
      <div className="my-6 flex items-center gap-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <span className="h-px flex-1 bg-border" />{t('auth.or')}<span className="h-px flex-1 bg-border" />
      </div>
      <div className="grid gap-2">
        {(Object.keys(OAUTH_PROVIDERS) as OAuthProvider[]).map((provider) => (
          <Button key={provider} type="button" variant="outline" size="tap" className="h-12 w-full"
            onClick={() => onSelect(provider)} disabled={disabled}>
            {t('auth.continueWith', { provider: OAUTH_PROVIDERS[provider].label })}
          </Button>
        ))}
      </div>
    </>
  );
}

/** A finished or blocked step: an icon, a message, and one way forward. */
export function AuthStatus({ icon: Icon, tone = 'brand', title, body, children }: {
  icon: LucideIcon; tone?: 'brand' | 'success' | 'warning'; title: string; body?: string; children?: React.ReactNode;
}) {
  return (
    <div role="status" className="text-center">
      <span aria-hidden className={cn('mx-auto mb-4 flex size-16 items-center justify-center rounded-3xl',
        tone === 'brand' && 'bg-brand-soft text-brand-ink', tone === 'success' && 'bg-success-soft text-success-ink',
        tone === 'warning' && 'bg-warning-soft text-warning-ink')}>
        <Icon className="size-8" />
      </span>
      <h1 className="text-xl font-bold">{title}</h1>
      {body && <p className="mt-2 text-pretty text-sm text-muted-foreground">{body}</p>}
      {children && <div className="mt-6 grid gap-2">{children}</div>}
    </div>
  );
}
