import type { Config, Layout } from 'plotly.js';
import { CHART_SEPARATORS } from '@/lib/format';

/** Cores do cockpit (tokens de globals.css) para os gráficos. */
export const CHART_COLORS = {
  fg: '#f7f7f7',
  muted: '#9e9ea6',
  grid: 'rgba(85, 85, 85, 0.45)',
  accent: '#7fd1c7',
  warn: '#e3b45f',
  danger: '#e2716b',
  series: ['#7fd1c7', '#e3b45f', '#a99cf0', '#6fb3e8', '#e2716b', '#c9d17f', '#f0a3c8'],
} as const;

const AXIS = { gridcolor: CHART_COLORS.grid, zeroline: false, color: CHART_COLORS.muted, linecolor: CHART_COLORS.grid };

/** Layout padrão; os eixos são mesclados (o gráfico só ajusta formato e título, não perde as cores). */
export function baseLayout(overrides: Partial<Layout> = {}): Partial<Layout> {
  const { xaxis, yaxis, ...rest } = overrides;
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: CHART_COLORS.fg, family: 'inherit', size: 12 },
    separators: CHART_SEPARATORS,
    margin: { l: 56, r: 16, t: 16, b: 40 },
    hovermode: 'x unified',
    legend: { orientation: 'h', y: -0.2, font: { color: CHART_COLORS.muted } },
    ...rest,
    xaxis: { ...AXIS, ...xaxis },
    yaxis: { ...AXIS, ...yaxis },
  };
}

/**
 * Nada sai da máquina (PRD-NF-01): sem o botão "Share chart" (envia o gráfico com os dados para a
 * nuvem da Plotly) nem "Edit in Chart Studio", e sem servidor de destino configurado.
 */
export const BASE_CONFIG: Partial<Config> = {
  displaylogo: false,
  responsive: true,
  showSendToCloud: false,
  plotlyServerURL: '',
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'toImage', 'sendChartToCloud'],
  locale: 'pt-BR',
};
