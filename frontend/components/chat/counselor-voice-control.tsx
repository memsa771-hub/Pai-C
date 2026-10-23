'use client';

/** Talking with PAI by voice. The session state lives in one hook; the
 * composer shows the voice button (Figma's "voice mode" bars) beside send,
 * and the status and live captions sit just above the composer. */

import { useEffect, useRef, useState } from 'react';
import { CounselorVoiceSession, type VoiceStatus } from '@/lib/counselor-voice';
import { cn } from '@/lib/utils';
import { VoiceBars } from './voice-bars';
import copy from './counselor-voice-copy.json';

const labels: Record<VoiceStatus, string> = copy.status;

export type CounselorVoice = ReturnType<typeof useCounselorVoice>;

export function useCounselorVoice({ conversation, senderName, senderId, onMessagePosted }: {
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

  // A different conversation ends the session and starts clean.
  useEffect(() => {
    setStatus('idle'); setDetail(''); setStudentCaption(''); setPaiCaption('');
    return () => {
      void session.current?.stop();
      session.current = null;
    };
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
  const ready = !!senderId && !!senderName.trim();
  return { status, detail, studentCaption, paiCaption, live, ready, start, stop };
}

/** The voice button inside the composer: starts a session, or ends a live one. */
export function VoiceModeButton({ voice }: { voice: CounselorVoice }) {
  const label = voice.live ? copy.end : voice.status === 'error' ? copy.retry : copy.start;
  return (
    <button type="button" onClick={() => void (voice.live ? voice.stop() : voice.start())}
      disabled={!voice.live && !voice.ready} aria-pressed={voice.live} aria-label={label} title={label}
      className={cn('flex size-11 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-[#f0f4fc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40',
        voice.live && 'bg-[#f0f4fc]')}>
      <VoiceBars live={voice.live} />
    </button>
  );
}

/** What the voice session is doing, and the live captions, above the composer. */
export function VoiceStatus({ voice }: { voice: CounselorVoice }) {
  if (voice.status === 'idle' && !voice.detail) return null;
  return (
    <div className="mb-2" aria-live="polite">
      <p className="text-sm font-medium text-muted-foreground" role="status">{labels[voice.status]}</p>
      {voice.detail && <p className="mt-1 text-xs font-medium text-danger-ink">{voice.detail}</p>}
      {(voice.studentCaption || voice.paiCaption) && voice.status !== 'idle' && (
        <div className="mt-2 max-h-24 space-y-1 overflow-y-auto rounded-2xl bg-muted/60 px-3 py-2 text-sm">
          {voice.studentCaption && <p><span className="font-semibold">{copy.student}:</span> {voice.studentCaption}</p>}
          {voice.paiCaption && <p><span className="font-semibold text-brand-ink">{copy.counselor}:</span> {voice.paiCaption}</p>}
        </div>
      )}
    </div>
  );
}
