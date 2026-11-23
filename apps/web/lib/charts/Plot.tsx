'use client';

import dynamic from 'next/dynamic';
import type { PlotProps } from './PlotClient';

/**
 * Gráfico do cockpit (ADR-12, PRD-UI-06): Plotly carregado sob demanda, sem SSR.
 * Lacunas são `null` nos dados e aparecem como quebra da linha (`connectgaps: false`, PRD-UI-05).
 */
const Plot = dynamic<PlotProps>(() => import('./PlotClient'), {
  ssr: false,
  loading: () => <p style={{ color: 'var(--fg-muted)', minHeight: 120 }}>Carregando gráfico…</p>,
});

export default Plot;
export type { PlotProps };
