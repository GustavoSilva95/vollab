'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * Assina uma media query. No servidor (e na hidratação) devolve `serverValue`.
 */
export default function useMediaQuery(query, serverValue = false) {
  const subscribe = useCallback(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    [query],
  );

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}
