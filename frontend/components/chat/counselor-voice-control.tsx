'use client';

import { useEffect, useRef, useState } from 'react';
import { Mic, PhoneOff, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CounselorVoiceSession, type VoiceStatus } from '@/lib/counselor-voice';

const labels: Record<VoiceStatus, string> = {
  idle: 'Talk to PAI',
  permission: 'Allow microphone…',
  connecting: 'Connecting…',
  listening: 'Listening',
  speaking: 'PAI is speaking',
  interrupted: 'Listening to you',
  reconnecting: 'Reconnecting…',
  error: 'Voice unavailable',
};

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

  return (
    <div className="mb-2 rounded-xl border border-border/70 bg-background/70 px-3 py-2" aria-live="polite">
      <div className="flex items-center gap-2">
        {status === 'idle' || status === 'error' ? (
          <Button type="button" size="sm" variant="outline" onClick={() => void start()} disabled={!senderId || !senderName.trim()}>
            {status === 'error' ? <RotateCcw className="mr-2 size-4" /> : <Mic className="mr-2 size-4" />}
            {status === 'error' ? 'Retry voice' : 'Talk to PAI'}
          </Button>
        ) : (
          <Button type="button" size="sm" variant="outline" onClick={() => void stop()}>
            <PhoneOff className="mr-2 size-4" /> End voice session
          </Button>
        )}
        <span className="text-xs text-muted-foreground" role="status">{labels[status]}</span>
      </div>
      {detail && <p className="mt-1 text-xs text-destructive">{detail}</p>}
      {(studentCaption || paiCaption) && status !== 'idle' && (
        <div className="mt-2 max-h-20 overflow-y-auto text-xs text-muted-foreground">
          {studentCaption && <p><span className="font-medium">You:</span> {studentCaption}</p>}
          {paiCaption && <p><span className="font-medium">PAI:</span> {paiCaption}</p>}
        </div>
      )}
    </div>
  );
}
