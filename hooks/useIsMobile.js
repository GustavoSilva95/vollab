'use client';

import useMediaQuery from './useMediaQuery';

const DEFAULT_BREAKPOINT = 640;

/** `true` em viewports estreitos (abaixo do breakpoint, em px). */
export default function useIsMobile(breakpoint = DEFAULT_BREAKPOINT) {
  return useMediaQuery(`(max-width: ${breakpoint - 0.02}px)`);
}

/** `true` quando o dispositivo principal não tem mouse (touch). */
export function useIsTouch() {
  return useMediaQuery('(hover: none), (pointer: coarse)');
}
