'use client';

import { useEffect, useState } from 'react';

/** Whether this tab is in front. Background tabs should hold no long-lived
 * connections: browsers allow only six per host over HTTP/1.1, and a few idle
 * tabs each keeping streams open is enough to stall every request. */
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(
    () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
  );
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return visible;
}
