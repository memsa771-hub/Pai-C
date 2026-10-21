'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import type { OperatorRun } from '@/lib/types';

const ACTIVE_POLL_MS = 4_000;
const IDLE_POLL_MS = 20_000;

/**
 * Resolve a race between two sources updating the same state (SSE, the
 * initial seed fetch, and the polling fallback can all land in any order —
 * a slow HTTP response can resolve after a newer SSE event already arrived).
 * Never apply an update that is older than what's already shown, keyed by
 * the server's own `updatedAt` rather than arrival order. A missing/absent
 * incoming run never clears an existing one — an empty read racing behind a
 * real update should not blank the indicator.
 */
function pickNewer(current: OperatorRun | null, incoming: OperatorRun | null): OperatorRun | null {
  if (!incoming) return current;
  if (!current) return incoming;
  const incomingTime = incoming.updatedAt ? Date.parse(incoming.updatedAt) : 0;
  const currentTime = current.updatedAt ? Date.parse(current.updatedAt) : 0;
  return incomingTime >= currentTime ? incoming : current;
}

type Listener = (run: OperatorRun | null) => void;

/**
 * One connection per tab for PAI Operator's run updates, however many
 * components show the "PAI is working…" state. Each component used to open
 * its own EventSource; with a chat stream as well, two or three tabs filled
 * the browser's six-connection limit per host and every request stalled.
 *
 * The hub opens on the first subscriber and closes with the last, and it lets
 * go of the stream while the tab is hidden, catching up on return.
 */
const hub = {
  listeners: new Set<Listener>(),
  run: null as OperatorRun | null,
  source: null as EventSource | null,
  timer: null as ReturnType<typeof setTimeout> | null,
  polling: false,

  publish(incoming: OperatorRun | null) {
    const next = pickNewer(this.run, incoming);
    if (next === this.run) return;
    this.run = next;
    this.listeners.forEach((listener) => listener(next));
  },

  async seed() {
    try {
      const { runs } = await workspaceApi.listOperatorRuns({ limit: 1 });
      this.publish(runs[0] ?? null);
      return runs[0] ?? null;
    } catch {
      // Best-effort: the stream or the polling fallback catches up.
      return null;
    }
  },

  async tick() {
    const latest = await this.seed();
    if (!this.polling) return;
    const working = latest && !['completed', 'needs_user_action', 'failed'].includes(latest.status);
    this.timer = setTimeout(() => void this.tick(), working ? ACTIVE_POLL_MS : IDLE_POLL_MS);
  },

  startPolling() {
    if (this.polling) return;
    this.polling = true;
    void this.tick();
  },

  stopPolling() {
    this.polling = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  },

  open() {
    if (this.source || this.polling) return;
    void this.seed();
    try {
      const source = new EventSource(workspaceApi.getOperatorEventsUrl());
      source.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data);
          if (event.type !== 'workspace.operator.run_updated') return;
          this.publish(workspaceApi.mapOperatorRun(event.payload));
        } catch {
          // malformed event
        }
      };
      source.onerror = () => {
        source.close();
        if (this.source === source) this.source = null;
        this.startPolling();
      };
      this.source = source;
    } catch {
      this.startPolling();
    }
  },

  close() {
    this.source?.close();
    this.source = null;
    this.stopPolling();
  },

  visibility: () => {
    if (!hub.listeners.size) return;
    if (document.visibilityState === 'hidden') hub.close();
    else hub.open();
  },

  subscribe(listener: Listener) {
    this.listeners.add(listener);
    listener(this.run);
    if (this.listeners.size === 1) {
      document.addEventListener('visibilitychange', this.visibility);
      if (document.visibilityState !== 'hidden') this.open();
    }
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) {
        document.removeEventListener('visibilitychange', this.visibility);
        this.close();
        this.run = null;
      }
    };
  },
};

/**
 * PAI Operator's most recent run — the read side of the "PAI is working…"
 * indicator. Realtime SSE first (Operator publishes
 * "workspace.operator.run_updated" on target "core"), polling only as the
 * fallback. This hook never simulates progress; it reflects only what the
 * server reported, through the one shared connection above.
 */
export function useOperatorStatus(enabled: boolean): OperatorRun | null {
  const [run, setRun] = useState<OperatorRun | null>(null);
  useEffect(() => {
    if (!enabled) {
      setRun(null);
      return;
    }
    return hub.subscribe(setRun);
  }, [enabled]);
  return run;
}
