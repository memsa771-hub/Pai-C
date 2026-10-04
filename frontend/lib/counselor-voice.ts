import { workspaceApi } from './api';

export type VoiceStatus = 'idle' | 'permission' | 'connecting' | 'listening' | 'speaking' | 'interrupted' | 'reconnecting' | 'error';

type TranscriptPart = { text: string; start: number; end: number };
type LiveEvent = {
  type: string;
  event_id?: string;
  delta?: string;
  start_ms?: number;
  end_ms?: number;
  offset_ms?: number;
  delegation?: { id?: string; target?: string };
  error?: { message?: string };
};

export interface VoiceCallbacks {
  status: (status: VoiceStatus, detail?: string) => void;
  transcript: (student: string, pai: string) => void;
  messagePosted: () => void;
}

const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Keep GPT-Live commentary updates short and coherent across languages. */
export function speechChunks(reply: string): string[] {
  const sentences = typeof Intl.Segmenter === 'function'
    ? Array.from(new Intl.Segmenter(undefined, { granularity: 'sentence' }).segment(reply), (part) => part.segment)
    : [reply];
  const chunks: string[] = [];
  let current = '';
  for (const sentence of sentences) {
    for (let remaining = sentence.trim(); remaining;) {
      const room = 350 - Array.from(current).length - (current ? 1 : 0);
      if (Array.from(remaining).length <= room) {
        current += (current ? ' ' : '') + remaining;
        break;
      }
      if (current) {
        chunks.push(current);
        current = '';
        continue;
      }
      const symbols = Array.from(remaining);
      chunks.push(symbols.slice(0, 350).join(''));
      remaining = symbols.slice(350).join('').trimStart();
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

/** OpenAI WebRTC is only the audio transport; Counselor work uses normal events. */
export class CounselorVoiceSession {
  private peer: RTCPeerConnection | null = null;
  private microphone: MediaStream | null = null;
  private audio: HTMLAudioElement | null = null;
  private events: RTCDataChannel | null = null;
  private closed = true;
  private started = false;
  private generation = 0;
  private parts: TranscriptPart[] = [];
  private lastDelegationOffset = 0;
  private seenDelegations = new Set<string>();
  private lastStudent = '';
  private lastPai = '';
  private speakingTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private startedTimer: ReturnType<typeof setTimeout> | null = null;
  private latestDelegation = '';
  private reconnecting = false;

  constructor(
    private conversation: string,
    private senderName: string,
    private senderId: string,
    private callbacks: VoiceCallbacks,
  ) {}

  async start(): Promise<void> {
    this.closed = false;
    await this.connect(false);
  }

  private async connect(reconnecting: boolean): Promise<void> {
    const generation = ++this.generation;
    this.started = false;
    this.callbacks.status(reconnecting ? 'reconnecting' : 'permission');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone is unavailable in this browser or insecure connection.');
      this.microphone = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (this.closed || generation !== this.generation) {
        this.microphone.getTracks().forEach((track) => track.stop());
        this.microphone = null;
        return;
      }
      this.callbacks.status(reconnecting ? 'reconnecting' : 'connecting');
      const peer = new RTCPeerConnection();
      this.peer = peer;
      const audio = document.createElement('audio');
      audio.autoplay = true;
      audio.setAttribute('playsinline', '');
      this.audio = audio;
      peer.addEventListener('track', (event) => {
        audio.srcObject = event.streams[0] || new MediaStream([event.track]);
        void audio.play().catch(() => this.callbacks.status('error', 'Tap to allow PAI audio playback.'));
      });
      for (const track of this.microphone.getAudioTracks()) peer.addTrack(track, this.microphone);
      const events = peer.createDataChannel('oai-events');
      this.events = events;
      events.addEventListener('message', ({ data }) => {
        if (generation !== this.generation || this.closed) return;
        try { this.onEvent(JSON.parse(String(data)) as LiveEvent, generation); }
        catch { /* Ignore an invalid provider event. */ }
      });
      events.addEventListener('close', () => {
        if (!this.closed && generation === this.generation) {
          if (this.started) void this.reconnect();
          else this.fail('Voice connection closed before it started. Please retry.');
        }
      });
      peer.addEventListener('connectionstatechange', () => {
        if (peer.connectionState === 'failed' && !this.closed && generation === this.generation) {
          if (this.started) void this.reconnect();
          else this.fail('Could not establish the voice connection. Please retry.');
        }
        if (peer.connectionState === 'disconnected' && !this.closed && generation === this.generation) {
          this.reconnectTimer = setTimeout(() => {
            if (peer.connectionState === 'disconnected') {
              if (this.started) void this.reconnect();
              else this.fail('Could not establish the voice connection. Please retry.');
            }
          }, 4000);
        }
      });
      await peer.setLocalDescription(await peer.createOffer());
      await this.waitForIce(peer);
      if (this.closed || generation !== this.generation) return;
      const offer = peer.localDescription?.sdp;
      if (!offer) throw new Error('Could not prepare the voice connection.');
      const answer = await workspaceApi.createCounselorVoiceSession(this.conversation, offer);
      if (this.closed || generation !== this.generation) return;
      // Install this before applying the answer: session.started can arrive immediately.
      this.startedTimer = setTimeout(() => {
        if (!this.closed && generation === this.generation) {
          this.fail('Voice did not start. Please retry.');
        }
      }, 15_000);
      await peer.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
      // The session creation request starts GPT-Live; do not send session.start.
    } catch (error) {
      if (this.closed || generation !== this.generation) return;
      const denied = error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError');
      this.fail(denied ? 'Allow microphone access to talk to PAI.' : 'Could not connect voice. Please retry.');
    }
  }

  private async waitForIce(peer: RTCPeerConnection): Promise<void> {
    if (peer.iceGatheringState === 'complete') return;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', check); reject(new Error('Voice connection timed out.')); }, 10_000);
      const check = () => {
        if (peer.iceGatheringState !== 'complete') return;
        clearTimeout(timer);
        peer.removeEventListener('icegatheringstatechange', check);
        resolve();
      };
      peer.addEventListener('icegatheringstatechange', check);
      check();
    });
  }

  private onEvent(event: LiveEvent, generation: number): void {
    if (event.type === 'session.started') {
      this.started = true;
      if (this.startedTimer) clearTimeout(this.startedTimer);
      this.startedTimer = null;
      this.callbacks.status('listening');
    } else if (event.type === 'session.input_transcript.delta' && event.delta) {
      this.parts.push({ text: event.delta, start: event.start_ms ?? 0, end: event.end_ms ?? 0 });
      this.lastStudent += event.delta;
      if (this.speakingTimer) {
        clearTimeout(this.speakingTimer);
        this.speakingTimer = null;
        this.callbacks.status('interrupted');
      } else this.callbacks.status('listening');
      this.callbacks.transcript(this.lastStudent, this.lastPai);
    } else if (event.type === 'session.output_transcript.delta' && event.delta) {
      this.lastPai += event.delta;
      this.callbacks.transcript(this.lastStudent, this.lastPai);
      this.callbacks.status('speaking');
      if (this.speakingTimer) clearTimeout(this.speakingTimer);
      this.speakingTimer = setTimeout(() => {
        if (!this.closed && generation === this.generation) this.callbacks.status('listening');
        this.speakingTimer = null;
      }, 1800);
    } else if (event.type === 'session.delegation.created' && event.delegation?.target === 'client' && event.delegation.id) {
      void this.handleDelegation(event.delegation.id, event.offset_ms ?? 0, generation);
    } else if (event.type === 'session.closed') {
      this.closed = true;
      ++this.generation;
      this.release();
      this.callbacks.status('idle');
    } else if (event.type === 'error') {
      this.callbacks.status('error', 'Voice connection error. Please retry.');
    }
  }

  private send(type: string, payload: Record<string, unknown>): void {
    if (this.events?.readyState === 'open') this.events.send(JSON.stringify({ type, event_id: crypto.randomUUID(), ...payload }));
  }

  private fail(message: string): void {
    this.closed = true;
    ++this.generation;
    this.release();
    this.callbacks.status('error', message);
  }

  private async handleDelegation(id: string, offset: number, generation: number): Promise<void> {
    if (this.seenDelegations.has(id)) return;
    this.seenDelegations.add(id);
    this.latestDelegation = id;
    // Transcripts can arrive after the delegation event; let the final fragments land.
    await pause(450);
    if (this.closed || generation !== this.generation) return;
    const transcript = this.parts
      .filter((part) => part.end > this.lastDelegationOffset && part.start <= offset + 150)
      .map((part) => part.text).join('').trim();
    this.lastDelegationOffset = Math.max(this.lastDelegationOffset, offset);
    this.parts = this.parts.filter((part) => part.end > offset - 500);
    this.lastStudent = '';
    this.lastPai = '';
    if (!transcript) {
      this.send('session.commentary.append', { delegation_id: id, content: 'I could not hear that clearly. Please say it again.' });
      return;
    }
    try {
      const posted = await workspaceApi.sendCounselorVoiceTurn(this.conversation, transcript, id, this.senderName, this.senderId);
      this.callbacks.messagePosted();
      const reply = await this.waitForCounselor(posted.id, id, generation);
      if (reply && !this.closed && generation === this.generation && id === this.latestDelegation) {
        for (const chunk of speechChunks(reply)) {
          this.send('session.commentary.append', { delegation_id: id, content: chunk });
        }
      }
    } catch (error) {
      if (this.closed || generation !== this.generation || id !== this.latestDelegation) return;
      this.callbacks.status('error', 'PAI could not answer right now. Please try again.');
      this.send('session.commentary.append', { delegation_id: id, content: 'I could not reach PAI right now. Please try again.' });
    }
  }

  private async waitForCounselor(after: string, id: string, generation: number): Promise<string | null> {
    const deadline = Date.now() + 90_000;
    while (!this.closed && generation === this.generation && Date.now() < deadline) {
      const page = await workspaceApi.pollEvents({
        after, type: 'workspace.message', limit: 100, channel: this.conversation,
      });
      for (const event of page.events) {
        if (event.source === 'openagents:pai' && event.metadata?.voice_delegation_id === id) {
          this.callbacks.messagePosted();
          const content = String(event.payload?.content || '');
          return content.startsWith('[Error]') ? 'I could not reach PAI right now. Please try again.' : content;
        }
      }
      if (page.has_more && page.events.length) after = page.events[page.events.length - 1].id;
      await pause(700);
    }
    throw new Error('PAI took too long to respond. Please try again.');
  }

  private async reconnect(): Promise<void> {
    if (this.closed || this.reconnecting) return;
    this.reconnecting = true;
    this.callbacks.status('reconnecting');
    ++this.generation;
    this.send('session.close', {});
    this.release();
    this.parts = [];
    this.lastDelegationOffset = 0;
    this.seenDelegations.clear();
    this.latestDelegation = '';
    try { await this.connect(true); }
    finally { this.reconnecting = false; }
  }

  async stop(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    ++this.generation;
    if (this.events?.readyState === 'open') {
      const events = this.events;
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, 3500);
        const closed = () => { clearTimeout(timer); resolve(); };
        events.addEventListener('message', ({ data }) => {
          try { if (JSON.parse(String(data)).type === 'session.closed') closed(); } catch { /* ignore */ }
        });
        events.send(JSON.stringify({ type: 'session.close', event_id: crypto.randomUUID() }));
      });
    }
    this.release();
    this.callbacks.status('idle');
  }

  private release(): void {
    if (this.speakingTimer) clearTimeout(this.speakingTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.startedTimer) clearTimeout(this.startedTimer);
    this.speakingTimer = null;
    this.reconnectTimer = null;
    this.startedTimer = null;
    this.microphone?.getTracks().forEach((track) => track.stop());
    this.events?.close();
    this.peer?.close();
    if (this.audio) this.audio.srcObject = null;
    this.microphone = null;
    this.events = null;
    this.peer = null;
    this.audio = null;
  }
}
