'use client';

/** The sign-in and onboarding frame from Figma ("PAI / Sign in / Refined" and
 * "PAI / Onboarding / 01–03"): a white column with a soft pattern, the PAI
 * logo and the form; beside it a pale-blue panel where PAI waves from a
 * portal above a chat prompt. The two columns always fill the screen; the
 * panel's artwork is drawn at its design size (716 × 852) and fitted inside
 * it. Phones and tablets show only the form, centred on the screen. */

import { useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import type { LucideIcon } from 'lucide-react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { useT } from '@/lib/i18n';
import { cn } from '@/lib/utils';

export type AuthPanel = 'sign-in' | 'name' | 'about' | 'location';

const PANEL_W = 716;
const PANEL_H = 852;

/** Scale that fits the panel's artwork (716 × 852) inside its column. */
function usePanelScale() {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      setScale(Math.min(width / PANEL_W, height / PANEL_H));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, []);
  return [ref, scale] as const;
}

/** The PAI logo as placed in the frame: a 100 × 63 crop of the logo artwork. */
function PaiLogo() {
  return (
    <div className="relative mx-auto h-[63px] w-[100px] [filter:drop-shadow(1.942px_1.942px_6.604px_rgb(0_0_0/0.25))]">
      {/* The design stacks the artwork four times to deepen its edges. */}
      {[0, 1, 2, 3].map((layer) => (
        <div key={layer} aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
          <img src="/auth/logo.png" alt="" className="absolute left-[-65.89%] top-[-1.4%] h-[156.27%] w-[232.32%] max-w-none" />
        </div>
      ))}
      <span className="sr-only">Placement AI</span>
    </div>
  );
}

/** Three short strokes beside PAI's waving hand. (x, y) is the top stroke's start. */
function MotionLines({ x, y }: { x: number; y: number }) {
  return (
    <>
      <div className="absolute flex h-[0.585px] w-[25px] items-center justify-center" style={{ left: x, top: y + 9 }}>
        <div className="flex-none rotate-[-1.34deg]">
          <div className="relative h-0 w-[25.007px]">
            <div className="absolute inset-[-0.5px_7.22%_-0.5px_-2%]"><img alt="" src="/auth/motion-1.svg" className="block size-full max-w-none" /></div>
          </div>
        </div>
      </div>
      <div className="absolute flex h-[4px] w-[23px] items-center justify-center" style={{ left: x, top: y }}>
        <div className="flex-none rotate-[9.87deg]">
          <div className="relative h-0 w-[23.345px]">
            <div className="absolute inset-[-0.5px_7.08%_-0.5px_-2.14%]"><img alt="" src="/auth/motion-2.svg" className="block size-full max-w-none" /></div>
          </div>
        </div>
      </div>
      <div className="absolute flex h-[3.675px] w-[23.203px] items-center justify-center" style={{ left: x + 1.72, top: y + 15.64 }}>
        <div className="flex-none -rotate-9">
          <div className="relative h-0 w-[23.492px]">
            <div className="absolute inset-[-0.5px_-0.95%_-0.5px_-2.13%]"><img alt="" src="/auth/motion-3.svg" className="block size-full max-w-none" /></div>
          </div>
        </div>
      </div>
    </>
  );
}

/** The chat prompt under PAI ("Prompt Panel / Blue glow"). Decorative. */
function PromptPanel({ text, chip, left, top }: { text: string; chip: string; left: number; top: number }) {
  const t = useT();
  return (
    <div className="absolute flex w-[588px] flex-col items-start gap-4 rounded-[32px] border-[1.3px] border-auth-prompt-line bg-white px-[22.7px] pb-[18px] pt-[22px] shadow-[0px_6px_14px_0px_rgba(15,51,140,0.08),0px_3px_22px_0px_rgba(20,84,242,0.25)]"
      style={{ left, top }}>
      <p className="min-h-[50px] w-[540px] text-[17px] font-bold leading-[25px] text-auth-prompt-ink">{text}</p>
      <div className="flex h-10 w-[540px] items-center justify-between overflow-clip">
        <div className="flex h-10 w-[202px] items-center gap-2.5 overflow-clip">
          <span className="flex size-[38px] items-center justify-center overflow-clip rounded-[19px] border border-auth-chip-line">
            <img alt="" src="/auth/plus.svg" className="size-[22px]" />
          </span>
          <span className="flex h-9 w-[154px] items-center gap-[7px] overflow-clip rounded-[18px] border border-auth-chip-line pl-2.5">
            <img alt="" src="/auth/compass.svg" className="size-[18px]" />
            <span className="whitespace-nowrap text-[14px] leading-normal text-auth-prompt-ink">{chip}</span>
            <img alt="" src="/auth/chevron-small.svg" className="size-3" />
          </span>
        </div>
        <div className="relative flex h-10 w-[244px] items-center gap-3 overflow-clip">
          <span className="flex h-9 w-[140px] items-center justify-center overflow-clip rounded-[18px] border border-auth-pill-line bg-auth-pill pl-3">
            <span className="whitespace-nowrap text-[14px] leading-normal text-auth-prompt-ink">{t('auth.previewModel')}</span>
          </span>
          <div className="absolute left-[163.7px] top-[0.7px] h-[36.906px] w-[75.755px] overflow-clip">
            <div className="absolute left-0 top-1/2 h-[29.137px] w-[21.367px] -translate-y-1/2">
              <span className="absolute inset-[0_34.62%] rounded-[19px] border-[0.943px] border-[rgba(0,0,0,0.28)] bg-auth-blue" />
              <span className="absolute inset-[19.05%_0_19.05%_73.08%] rounded-[19px] border-[0.943px] border-[rgba(0,0,0,0.29)] bg-auth-blue" />
              <span className="absolute inset-[19.05%_73.08%_19.05%_0] rounded-[19px] border-[0.943px] border-[rgba(0,0,0,0.28)] bg-auth-blue" />
            </div>
            <img alt="" src="/auth/send.svg" className="absolute left-[42.79px] top-[6.98px] h-[25px] w-[26px]" />
          </div>
        </div>
      </div>
    </div>
  );
}

/** PAI rising out of the portal, as on the onboarding frames. */
function OnboardingMascot({ lines }: { lines?: { x: number; y: number } }) {
  return (
    <div className="absolute left-[67.42px] top-[127px] h-[445.44px] w-[581.16px]">
      <div className="absolute left-[166.53px] top-[-13.34px] h-[459.286px] w-[272.06px]">
        <div className="absolute inset-[-4.55%_-7.67%]"><img alt="" src="/auth/portal-glow.svg" className="block size-full max-w-none" /></div>
      </div>
      <img alt="" src="/auth/portal.svg" className="absolute left-[167.04px] top-[-12.76px] h-[462.84px] w-[271.44px] max-w-none" />
      <div className="absolute left-0 top-0 h-[444.28px] w-[581.16px] overflow-clip">
        <img alt="" src="/auth/mascot.png" width={580} height={444.28} className="absolute left-[9.28px] top-[32.48px] h-[444.28px] w-[580px] max-w-none" />
        {lines && <MotionLines {...lines} />}
      </div>
    </div>
  );
}

/** The quiet white arc in the panel's top-right corner, at design size. */
function PanelBackdrop() {
  return <img alt="" src="/auth/arc.svg" className="absolute left-[254px] top-[-320px] size-[700px] max-w-none" />;
}

/** What sits on the panel (PAI, the portal, the heading and the chat prompt), at design size. */
function PanelContent({ panel, prompt }: { panel: AuthPanel; prompt: string }) {
  const t = useT();
  if (panel === 'sign-in') {
    return (
      <>
        <div className="absolute left-[244.56px] top-[221.5px] h-[395.936px] w-[234.534px]">
          <div className="absolute inset-[-4.55%_-7.67%]"><img alt="" src="/auth/portal-glow-sign-in.svg" className="block size-full max-w-none" /></div>
        </div>
        <img alt="" src="/auth/portal-sign-in.svg" className="absolute left-[245px] top-[222px] h-[399px] w-[234px] max-w-none" />
        <div className="absolute left-[101px] top-[233px] h-[383px] w-[501px] overflow-clip">
          <img alt="" src="/auth/mascot-sign-in.png" width={500} height={383} className="absolute left-2 top-7 h-[383px] w-[500px] max-w-none" />
        </div>
        <div className="absolute left-16 top-[54px] flex w-[588px] flex-col items-start gap-3 overflow-clip">
          <p className="w-[588px] whitespace-pre-line text-[38px] font-bold leading-[1.45] text-auth-heading">{t('auth.panelTitle')}</p>
          <p className="w-[588px] text-[14px] leading-[1.45] text-auth-sub">{t('auth.panelSubtitle')}</p>
        </div>
        <PromptPanel text={prompt} chip={t('auth.previewChip')} left={64} top={677} />
        <MotionLines x={189} y={412} />
      </>
    );
  }
  const step = panel === 'about' ? '2' : '3';
  return (
    <>
      {/* Steps 2–3: the orbit around PAI and two small accents. */}
      {panel !== 'name' && <img alt="" src="/auth/orbit.svg" className="absolute left-0 top-0 h-[852px] w-[716px] max-w-none" />}
      <OnboardingMascot lines={panel === 'about' ? { x: 112.58, y: 203 } : panel === 'location' ? { x: 110.58, y: 198 } : undefined} />
      <PromptPanel text={prompt} chip={t('onboarding.chip')} left={69} top={656} />
      {panel === 'name' && <MotionLines x={177} y={336} />}
      {panel === 'about' && <MotionLines x={380} y={453} />}
      {panel !== 'name' && (
        <div className="absolute left-16 top-[35px] flex w-[588px] flex-col items-start gap-1.5 font-bold">
          <p className="whitespace-nowrap text-[11px] leading-[22px] tracking-[1.1px] text-auth-blue">{t(`onboarding.steps.${step}.eyebrow` as never)}</p>
          <p className="w-[588px] text-[27px] leading-[34px] text-auth-heading">{t(`onboarding.steps.${step}.heading` as never)}</p>
        </div>
      )}
    </>
  );
}

/** One frame for every sign-in and onboarding screen. */
export function AuthShell({ title, subtitle, panel = 'sign-in', prompt, logoGap = 22, links = false, children, footer }: {
  title?: string;
  subtitle?: string;
  /** Which Figma frame's panel to show beside the form. */
  panel?: AuthPanel;
  /** The line in the chat prompt under PAI. */
  prompt?: string;
  /** Space between the logo and the form, as on the frame. */
  logoGap?: number;
  /** Privacy policy and terms at the foot of the form column (sign-in frame). */
  links?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const t = useT();
  const [ref, scale] = usePanelScale();
  const design = { width: PANEL_W, height: PANEL_H };
  return (
    <div className="auth-frame min-h-svh w-full bg-auth-page font-display text-auth-ink lg:flex lg:h-svh lg:overflow-hidden">
      <main className="relative flex min-h-svh min-w-0 flex-col lg:min-h-0 lg:w-[47.5%] lg:overflow-y-auto">
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[url(/auth/pattern.png)] bg-[length:684px_auto] bg-repeat opacity-10" />
        <div className="relative mx-auto flex w-full max-w-[442px] flex-1 flex-col justify-center px-4 py-10 lg:py-[var(--auth-pad)]">
          <div style={{ marginBottom: `calc(${logoGap}px * var(--auth-logo-scale))` }}><PaiLogo /></div>
          {(title || subtitle) && (
            <div className="mb-[var(--auth-gap)] flex flex-col items-center gap-2 text-center leading-[1.45]">
              {title && <h1 className="w-full text-[length:var(--auth-title)] font-bold text-auth-ink">{title}</h1>}
              {subtitle && <p className="w-full text-[16px] text-auth-muted">{subtitle}</p>}
            </div>
          )}
          {children}
          {footer && <div className="mt-[var(--auth-gap)] flex flex-wrap items-start justify-center gap-[5px] text-[13px] leading-[1.45]">{footer}</div>}
        </div>
        {links && (
          <div className="relative flex justify-center gap-6 pb-10 text-[12px] leading-[1.45] text-auth-muted lg:pb-[calc(var(--auth-pad)+8px)]">
            <span>{t('auth.privacyPolicy')}</span>
            <span>{t('auth.termsOfUse')}</span>
          </div>
        )}
      </main>
      {/* Laptops and up: the panel fills its column, PAI and the prompt fitted
          inside it. Phones and tablets show only the form, centred. */}
      <aside aria-label={t('auth.previewLabel')} className="hidden lg:block lg:w-[52.5%] lg:pb-[25px] lg:pr-[40px] lg:pt-[23px]">
        <div ref={ref} aria-hidden
          className={cn('relative size-full overflow-clip rounded-[24px]', panel === 'about' || panel === 'location' ? 'bg-auth-panel-alt' : 'bg-auth-panel', !scale && 'invisible')}>
          <div className="absolute right-0 top-0 origin-top-right" style={{ ...design, transform: `scale(${scale || 1})` }}>
            <PanelBackdrop />
          </div>
          <div className="absolute left-1/2 top-1/2" style={{ ...design, transform: `translate(-50%, -50%) scale(${scale || 1})` }}>
            <PanelContent panel={panel} prompt={prompt ?? t('auth.previewPrompt')} />
          </div>
        </div>
      </aside>
    </div>
  );
}

/** Label + control + optional hint/error, wired for screen readers. `md` is
 * the onboarding label (15px), `sm` the sign-in label (14px). */
export function AuthField({ label, hint, error, size = 'sm', children }: {
  label: string;
  hint?: string;
  error?: string | null;
  size?: 'sm' | 'md';
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => React.ReactNode;
}) {
  const id = useId();
  const described = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className={size === 'md' ? 'text-[15px] font-bold leading-[22px] text-auth-label' : 'text-[14px] font-bold leading-[1.45] text-auth-ink'}>{label}</label>
      {children({ id, 'aria-describedby': described, 'aria-invalid': error ? true : undefined })}
      {error ? <p id={`${id}-error`} className="flex items-center gap-1.5 text-xs font-medium text-danger-ink"><AlertCircle aria-hidden className="size-3.5" />{error}</p>
        : hint ? <p id={`${id}-hint`} className="text-[12px] leading-[22px] text-auth-muted">{hint}</p> : null}
    </div>
  );
}

export const isEmail = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

/** The frame's text input: 52px tall, 12px corners, a quiet blue-grey border. */
export const authInputClass = 'h-[var(--auth-control)] w-full rounded-[12px] border border-auth-line bg-white px-4 text-[16px] font-normal text-auth-label shadow-none placeholder:text-[14px] placeholder:text-auth-placeholder focus-visible:border-auth-blue focus-visible:ring-2 focus-visible:ring-auth-blue/20 aria-invalid:border-danger';

export function PasswordInput({ className, ...props }: React.ComponentProps<typeof Input>) {
  const t = useT();
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? 'text' : 'password'} className={cn(authInputClass, 'pe-12', className)} />
      <button type="button" onClick={() => setVisible(!visible)} aria-pressed={visible} aria-label={t('auth.showPassword')}
        className="absolute inset-y-0 end-0 flex w-12 items-center justify-center rounded-e-[12px]">
        <img alt="" src="/auth/eye.svg" className="size-5" />
      </button>
    </div>
  );
}

export function AuthAlert({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-[12px] bg-danger-soft px-3 py-2.5 text-xs font-medium text-danger-ink">
      <AlertCircle aria-hidden className="mt-px size-4 shrink-0" />{children}
    </p>
  );
}

const primaryButton = 'flex h-[var(--auth-control)] w-full items-center justify-center gap-2 overflow-clip rounded-[12px] bg-auth-blue text-[20px] font-bold leading-[28px] text-white shadow-[0px_3px_10px_0px_rgba(18,51,128,0.13)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60';

/** Always pressable; forms validate on submit and say exactly what is missing. */
export function SubmitButton({ busy, busyLabel, children }: {
  busy: boolean; busyLabel: string; children: React.ReactNode;
}) {
  return (
    <button type="submit" className={primaryButton} disabled={busy} aria-busy={busy}>
      {busy ? <><Loader2 aria-hidden className="size-5 animate-spin" />{busyLabel}</> : children}
    </button>
  );
}

/** A link styled like the primary button, for status screens. */
export function InkLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className={primaryButton}>{children}</Link>;
}

/** The blue link in the line under a form ("Create account"). */
export function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  // The padding widens the tap target without moving anything.
  return <Link href={href} className="-my-3 py-3 font-bold text-auth-blue hover:underline">{children}</Link>;
}

/** "Continue with Google", with Google's mark as drawn in the frame. */
export function GoogleButton({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex h-[var(--auth-control)] w-full items-center justify-center gap-2.5 overflow-clip rounded-[12px] border border-auth-google-line bg-auth-google text-[20px] font-bold leading-[28px] text-auth-ink shadow-[0px_1px_3px_0px_rgba(18,51,128,0.06)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60">
      <img alt="" src="/auth/google.svg" className="size-7" />{label}
    </button>
  );
}

export function OrDivider() {
  const t = useT();
  return (
    <div className="flex items-center justify-center gap-4">
      <span aria-hidden className="h-px max-w-[135px] flex-1 bg-auth-divider" />
      <span className="whitespace-nowrap text-[12px] leading-[1.45] text-auth-muted">{t('auth.or')}</span>
      <span aria-hidden className="h-px max-w-[135px] flex-1 bg-auth-divider" />
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
        tone === 'neutral' && 'bg-auth-panel text-auth-blue', tone === 'success' && 'bg-success-soft text-success-ink',
        tone === 'warning' && 'bg-warning-soft text-warning-ink')}>
        <Icon className="size-7" />
      </span>
      <h1 className="text-[34px] font-bold leading-[1.45] text-auth-ink">{title}</h1>
      {body && <p className="mt-2 text-pretty text-[16px] leading-[1.45] text-auth-muted">{body}</p>}
      {children && <div className="mt-7 grid gap-3">{children}</div>}
    </div>
  );
}
