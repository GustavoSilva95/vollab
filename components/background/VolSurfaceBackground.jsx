'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import dynamic from 'next/dynamic';
import volSurfaceConfig from '@/lib/volSurfaceConfig';
import usePrefersReducedMotion from '@/hooks/usePrefersReducedMotion';
import usePageVisibility from '@/hooks/usePageVisibility';
import useIsMobile, { useIsTouch } from '@/hooks/useIsMobile';
import styles from './VolSurfaceBackground.module.css';

// three.js só no cliente e fora do bundle inicial.
const VolSurfaceScene = dynamic(() => import('./VolSurfaceScene'), {
  ssr: false,
  loading: () => null,
});

let webglSupportCache = null;

function detectWebGL() {
  if (webglSupportCache === null) {
    try {
      const canvas = document.createElement('canvas');
      webglSupportCache = Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
    } catch {
      webglSupportCache = false;
    }
  }
  return webglSupportCache;
}

const noopSubscribe = () => () => {};

/**
 * Fundo fixo da home: gradiente em CSS (sempre presente, sem layout shift) e,
 * por cima, o canvas WebGL com a superfície de volatilidade.
 * Renderize dentro da seção hero: o sentinela abaixo mede se o hero está visível.
 */
export default function VolSurfaceBackground() {
  const config = volSurfaceConfig;
  const layerRef = useRef(null);
  const sentinelRef = useRef(null);

  const hasWebGL = useSyncExternalStore(noopSubscribe, detectWebGL, () => false);
  const reducedMotion = usePrefersReducedMotion();
  const pageVisible = usePageVisibility();
  const isMobile = useIsMobile(config.mobileBreakpoint);
  const isTouch = useIsTouch();

  const [inView, setInView] = useState(true);
  const [ready, setReady] = useState(false);

  // Pausa quando o hero sai da viewport.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return undefined;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting));
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);

  // Desvanece o fundo conforme o scroll (escrita direta no estilo, sem re-render).
  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return undefined;
    let frame = 0;

    const update = () => {
      frame = 0;
      const distance = window.innerHeight * config.scrollFadeViewports;
      const progress = Math.min(window.scrollY / distance, 1);
      layer.style.setProperty('--scroll-fade', String(1 - progress));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };

    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [config.scrollFadeViewports]);

  const animate = !reducedMotion;
  let frameloop = 'always';
  if (!animate) frameloop = 'demand';
  else if (!pageVisible || !inView) frameloop = 'never';

  return (
    <>
      <div ref={sentinelRef} className={styles.sentinel} aria-hidden="true" />
      <div
        ref={layerRef}
        className={styles.layer}
        data-ready={ready || undefined}
        aria-hidden="true"
      >
        <div className={styles.fallback} />
        {hasWebGL && (
          <div className={styles.canvasWrap}>
            <VolSurfaceScene
              config={config}
              frameloop={frameloop}
              animate={animate}
              isMobile={isMobile}
              parallaxEnabled={animate && !isTouch}
              onReady={() => setReady(true)}
            />
          </div>
        )}
      </div>
    </>
  );
}
