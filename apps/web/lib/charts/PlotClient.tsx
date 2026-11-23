'use client';

import { useEffect, useRef } from 'react';
import type { Config, Data, Layout } from 'plotly.js';
import Plotly from './plotly';
import { BASE_CONFIG, baseLayout } from './theme';

export interface PlotProps {
  data: Data[];
  layout?: Partial<Layout>;
  config?: Partial<Config>;
  height?: number;
  /** Rótulo acessível: o gráfico é desenhado em canvas/SVG sem texto navegável. */
  ariaLabel: string;
}

/** Desenha com `Plotly.react` e libera os recursos ao desmontar. Só roda no navegador. */
export default function PlotClient({ data, layout, config, height = 320, ariaLabel }: PlotProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    void Plotly.react(el, data, baseLayout({ height, ...layout }), { ...BASE_CONFIG, ...config });
  }, [data, layout, config, height]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ width: '100%', minHeight: height }} />;
}
