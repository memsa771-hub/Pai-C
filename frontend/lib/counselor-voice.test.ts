import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  createCounselorVoiceSession: vi.fn(),
  sendCounselorVoiceTurn: vi.fn(),
  pollEvents: vi.fn(),
}));
vi.mock('./api', () => ({ workspaceApi: api }));

import { CounselorVoiceSession, speechChunks, type VoiceStatus } from './counselor-voice';

class FakeChannel {
  readyState = 'open';
  sent: Array<Record<string, unknown>> = [];
  listeners: Record<string, Array<(event: { data: string }) => void>> = {};
  addEventListener(type: string, callback: (event: { data: string }) => void) {
    (this.listeners[type] ||= []).push(callback);
  }
  emit(value: Record<string, unknown>) {
    for (const callback of this.listeners.message || []) callback({ data: JSON.stringify(value) });
  }
  send(data: string) {
    const value = JSON.parse(data);
    this.sent.push(value);
    if (value.type === 'session.close') this.emit({ type: 'session.closed' });
  }
  close() {
    this.readyState = 'closed';
    for (const callback of this.listeners.close || []) callback({ data: '' });
  }
}

class FakePeer {
  static current: FakePeer;
  iceGatheringState = 'complete';
  connectionState = 'connected';
  localDescription = { sdp: 'offer-sdp-with-enough-length' };
  channel = new FakeChannel();
  constructor() { FakePeer.current = this; }
  addEventListener() {}
  addTrack() {}
  createDataChannel() { return this.channel; }
  async createOffer() { return { type: 'offer', sdp: this.localDescription.sdp }; }
  async setLocalDescription() {}
  async setRemoteDescription() {}
  close() {}
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('Counselor voice', () => {
  it('keeps complete short sentences together for spoken replies', () => {
    const result = speechChunks('First, compare the courses. Then check the cost and funding.');
    expect(result).toEqual(['First, compare the courses. Then check the cost and funding.']);
    expect(speechChunks('A'.repeat(800)).every((part) => Array.from(part).length <= 350)).toBe(true);
  });

  it('stops on session setup failure instead of reconnecting forever', async () => {
    vi.stubGlobal('RTCPeerConnection', FakePeer);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({
      getAudioTracks: () => [{ stop: vi.fn() }], getTracks: () => [{ stop: vi.fn() }],
    }) } });
    vi.stubGlobal('document', { createElement: () => ({
      autoplay: false, setAttribute: vi.fn(), play: vi.fn(), srcObject: null,
    }) });
    api.createCounselorVoiceSession.mockRejectedValueOnce(new Error('API 400'));
    const statuses: VoiceStatus[] = [];
    const voice = new CounselorVoiceSession('pai-counselor', 'Student', 'owner', {
      status: (value) => statuses.push(value), transcript: vi.fn(), messagePosted: vi.fn(),
    });
    await voice.start();
    await Promise.resolve();
    expect(statuses.at(-1)).toBe('error');
    expect(api.createCounselorVoiceSession).toHaveBeenCalledTimes(1);
  });

  it('posts transcript through Counselor, speaks its matching reply, supports interruption and closes', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('RTCPeerConnection', FakePeer);
    vi.stubGlobal('navigator', {
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({
        getAudioTracks: () => [{ stop: vi.fn() }],
        getTracks: () => [{ stop: vi.fn() }],
      }) },
    });
    vi.stubGlobal('document', { createElement: () => ({
      autoplay: false, setAttribute: vi.fn(), play: vi.fn().mockResolvedValue(undefined), srcObject: null,
    }) });
    api.createCounselorVoiceSession.mockResolvedValue({ session_id: 'live-1', sdp: 'answer' });
    api.sendCounselorVoiceTurn
      .mockResolvedValueOnce({ id: 'student-event' })
      .mockResolvedValueOnce({ id: 'student-event-2' });
    api.pollEvents.mockImplementation(async ({ after }: { after: string }) => ({
      events: [{
        id: `reply-${after}`, source: 'openagents:pai',
        metadata: { voice_delegation_id: after === 'student-event' ? 'delegate-1' : 'delegate-2' },
        payload: { content: after === 'student-event'
          ? 'That course fits your goal; let us check the costs.'
          : 'Your budget changes the shortlist.' },
      }], has_more: false,
    }));
    const statuses: VoiceStatus[] = [];
    const voice = new CounselorVoiceSession('pai-counselor', 'Student', 'owner', {
      status: (value) => statuses.push(value),
      transcript: vi.fn(), messagePosted: vi.fn(),
    });
    await voice.start();
    const channel = FakePeer.current.channel;
    channel.emit({ type: 'session.started' });
    channel.emit({ type: 'session.output_transcript.delta', delta: 'Tell me more', start_ms: 1, end_ms: 100 });
    channel.emit({ type: 'session.input_transcript.delta', delta: 'Should I study CS?', start_ms: 100, end_ms: 800 });
    channel.emit({ type: 'session.delegation.created', offset_ms: 850, delegation: { id: 'delegate-1', target: 'client' } });
    await vi.advanceTimersByTimeAsync(500);
    expect(api.sendCounselorVoiceTurn).toHaveBeenCalledWith('pai-counselor', 'Should I study CS?', 'delegate-1', 'Student', 'owner', 'live-1');
    expect(channel.sent).toEqual(expect.arrayContaining([expect.objectContaining({
      type: 'session.commentary.append', delegation_id: 'delegate-1',
      content: 'That course fits your goal; let us check the costs.',
    })]));
    channel.emit({ type: 'session.input_transcript.delta', delta: 'My budget is lower.', start_ms: 1000, end_ms: 1500 });
    channel.emit({ type: 'session.delegation.created', offset_ms: 1550, delegation: { id: 'delegate-2', target: 'client' } });
    await vi.advanceTimersByTimeAsync(500);
    expect(api.sendCounselorVoiceTurn).toHaveBeenNthCalledWith(2, 'pai-counselor', 'My budget is lower.', 'delegate-2', 'Student', 'owner', 'live-1');
    expect(channel.sent).toEqual(expect.arrayContaining([expect.objectContaining({
      type: 'session.commentary.append', delegation_id: 'delegate-2', content: 'Your budget changes the shortlist.',
    })]));
    expect(statuses).toContain('interrupted');
    await voice.stop();
    expect(channel.sent.at(-1)?.type).toBe('session.close');
    expect(statuses.at(-1)).toBe('idle');
  });
});
