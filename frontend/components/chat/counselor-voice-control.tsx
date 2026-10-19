'use client';

import { useEffect, useRef, useState } from 'react';
import { Mic, PhoneOff, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CounselorVoiceSession, type VoiceStatus } from '@/lib/counselor-voice';
import copy from './counselor-voice-copy.json';

const labels: Record<VoiceStatus, string> = copy.status;

export function CounselorVoiceControl({
  conversation, senderName, senderId, onMessagePosted,
}: {
  conversation: string;
  senderName: string;
  senderId: string;
  onMessagePosted: () => void;
}) {
  const session = useRef<CounselorVoiceSession | null>(null);
  const [status, setStatus] = useState<VoiceStatus>('idle');
  const [detail, setDetail] = useState('');
  const [studentCaption, setStudentCaption] = useState('');
  const [paiCaption, setPaiCaption] = useState('');

  useEffect(() => () => {
    void session.current?.stop();
    session.current = null;
  }, [conversation]);

  const start = async () => {
    if (session.current) await session.current.stop();
    setDetail('');
    setStudentCaption('');
    setPaiCaption('');
    const next = new CounselorVoiceSession(conversation, senderName, senderId, {
      status: (value, message) => { setStatus(value); setDetail(message || ''); },
      transcript: (student, pai) => { setStudentCaption(student); setPaiCaption(pai); },
      messagePosted: onMessagePosted,
    });
    session.current = next;
    await next.start();
  };

  const stop = async () => {
    const current = session.current;
    session.current = null;
    await current?.stop();
    setStudentCaption('');
    setPaiCaption('');
  };

  const live = status !== 'idle' && status !== 'error';
  return (
    <div className="mb-2" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        {live ? (
          <Button type="button" size="tap" variant="soft" onClick={() => void stop()} className="rounded-full ps-1.5">
            <span className="relative flex size-8 items-center justify-center rounded-full bg-danger text-white">
              <span aria-hidden className="absolute inset-0 animate-ping rounded-full bg-danger/40" />
              <PhoneOff className="relative size-4" />
            </span>
            {copy.end}
          </Button>
        ) : (
          <Button type="button" size="tap" variant="soft" onClick={() => void start()} disabled={!senderId || !senderName.trim()} className="rounded-full ps-1.5">
            <span className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-[var(--hero-from)] to-[var(--hero-via)] text-white">
              {status === 'error' ? <RotateCcw className="size-4" /> : <Mic className="size-4" />}
            </span>
            {status === 'error' ? copy.retry : copy.start}
          </Button>
        )}
        {status !== 'idle' && <span className="text-sm font-medium text-muted-foreground" role="status">{labels[status]}</span>}
      </div>
      {detail && <p className="mt-1 text-xs font-medium text-danger-ink">{detail}</p>}
      {(studentCaption || paiCaption) && status !== 'idle' && (
        <div className="mt-2 max-h-24 space-y-1 overflow-y-auto rounded-2xl bg-muted/60 px-3 py-2 text-sm">
          {studentCaption && <p><span className="font-semibold">{copy.student}:</span> {studentCaption}</p>}
          {paiCaption && <p><span className="font-semibold text-brand-ink">{copy.counselor}:</span> {paiCaption}</p>}
        </div>
      )}
    </div>
  );
}
