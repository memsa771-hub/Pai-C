'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import type { UploadOptions } from '@/lib/os-documents';

const OFF: UploadOptions = { one_upload: false };

/** Whether the one upload entry point is on (P1-T7, D-y5). Off while loading, on any error, and for any answer that
 * is not a full "on" one: every screen then renders exactly as it did before. */
export function useUploadOptions(enabled = true): UploadOptions {
  const [options, setOptions] = useState<UploadOptions>(OFF);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    workspaceApi.getUploadOptions().then(
      (o) => { if (active && o && o.one_upload === true && Array.isArray(o.doc_types) && o.text) setOptions(o); },
      () => {},
    );
    return () => { active = false; };
  }, [enabled]);
  return options;
}
