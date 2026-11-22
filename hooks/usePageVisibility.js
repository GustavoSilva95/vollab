'use client';

import { useSyncExternalStore } from 'react';

function subscribe(onChange) {
  document.addEventListener('visibilitychange', onChange);
  return () => document.removeEventListener('visibilitychange', onChange);
}

/** `true` enquanto a aba está visível. */
export default function usePageVisibility() {
  return useSyncExternalStore(
    subscribe,
    () => document.visibilityState === 'visible',
    () => true,
  );
}
