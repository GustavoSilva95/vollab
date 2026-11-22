/**
 * Rótulos em português da coleta (PRD §8.1, ADR-16). Só texto: números e datas são
 * formatados em `lib/format` (PRD-UI-03).
 */
import type { GapOut, ItemOut, RunSummary } from '@vollab/api-types';

export type ItemGroup = ItemOut['group'];
export type GapKind = GapOut['kind'];
export type RunStatus = RunSummary['status'];

export const GROUP_LABELS: Record<ItemGroup, string> = {
  cotahist_annual: 'COTAHIST anual (OHLC de 1 ano)',
  cotahist_daily: 'COTAHIST diário (OHLC e cadastro de séries)',
  selic: 'Selic (Banco Central)',
  dividends: 'Proventos (Yahoo, histórico)',
  underlying_trades: 'Negócios do ativo-objeto',
  option_trades: 'Negócios das opções elegíveis',
};

/** Ordem de execução (PRD-NF-04): COTAHIST → referência → ativo-objeto → opções. */
export const GROUP_ORDER: readonly ItemGroup[] = [
  'cotahist_annual',
  'cotahist_daily',
  'selic',
  'dividends',
  'underlying_trades',
  'option_trades',
];

export const GAP_LABELS: Record<GapKind, string> = {
  missing_bar: 'Sem OHLC oficial',
  r4_diverged: 'R4 diverge do oficial',
  calendar_alert: 'Alerta de calendário',
  cotahist_failed: 'COTAHIST com falha',
  underlying_trades_failed: 'Negócios do ativo com falha',
  options_failed: 'Opções com falha',
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Na fila do worker',
  running: 'Em andamento',
  succeeded: 'Concluída',
  partial: 'Concluída com falhas',
  interrupted: 'Interrompida',
  failed: 'Falhou',
};

export type Tone = 'ok' | 'warn' | 'danger' | 'muted';

export const RUN_STATUS_TONE: Record<RunStatus, Tone> = {
  queued: 'muted',
  running: 'ok',
  succeeded: 'ok',
  partial: 'warn',
  interrupted: 'warn',
  failed: 'danger',
};

export const ACTIVE_STATUSES: readonly RunStatus[] = ['queued', 'running'];

export function isActive(run: Pick<RunSummary, 'status'> | null | undefined): boolean {
  return run != null && ACTIVE_STATUSES.includes(run.status);
}

/** Mensagem de erro do engine (RFC 9457) para exibição; nunca mostra pilha nem objeto cru. */
export function problemMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  return fallback;
}
