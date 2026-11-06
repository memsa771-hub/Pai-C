'use client';

import { useCallback, useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { UPLOAD_TEXT_KEYS, type UploadOptions } from '@/lib/os-documents';

const OFF: UploadOptions = { one_upload: false };

/** The answer as a screen may use it: a full "on" answer (every text key present), else off. */
export function readUploadOptions(o: UploadOptions | null | undefined): UploadOptions {
  if (!o || o.one_upload !== true || !Array.isArray(o.doc_types) || !o.text) return OFF;
  const text = o.text as Record<string, unknown>;
  return UPLOAD_TEXT_KEYS.every((k) => typeof text[k] === 'string' && text[k]) ? o : OFF;
}

/** Whether the one upload entry point is on (P1-T7, D-y5), and a way to ask again. Off while loading, on any error,
 * and for any answer that is not a full "on" one: every screen then renders exactly as it did before. */
export function useUploadOptionsState(enabled = true): { options: UploadOptions; refresh: () => Promise<UploadOptions> } {
  const [options, setOptions] = useState<UploadOptions>(OFF);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    workspaceApi.getUploadOptions().then(
      (o) => { if (active) setOptions(readUploadOptions(o)); },
      () => {},
    );
    return () => { active = false; };
  }, [enabled]);
  const refresh = useCallback(async () => {
    try {
      const next = readUploadOptions(await workspaceApi.getUploadOptions());
      setOptions(next);
      return next;
    } catch {
      return OFF;
    }
  }, []);
  return { options, refresh };
}

export function useUploadOptions(enabled = true): UploadOptions {
  return useUploadOptionsState(enabled).options;
}
