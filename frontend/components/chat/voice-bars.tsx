import { cn } from '@/lib/utils';

/** The "voice mode" mark from Figma: three rounded blue bars, the middle one
 * tallest. While a voice session is live the bars breathe. */
export function VoiceBars({ live = false, className }: { live?: boolean; className?: string }) {
  const bar = 'absolute rounded-[19px] border-[0.943px] bg-[#155eef]';
  return (
    <span aria-hidden className={cn('relative block h-[29.137px] w-[21.367px]', className)}>
      <span className={cn(bar, 'inset-[0_34.62%] border-[rgba(0,0,0,0.28)]', live && 'animate-pulse')} />
      <span className={cn(bar, 'inset-[19.05%_0_19.05%_73.08%] border-[rgba(0,0,0,0.29)]', live && 'animate-pulse [animation-delay:150ms]')} />
      <span className={cn(bar, 'inset-[19.05%_73.08%_19.05%_0] border-[rgba(0,0,0,0.28)]', live && 'animate-pulse [animation-delay:300ms]')} />
    </span>
  );
}
