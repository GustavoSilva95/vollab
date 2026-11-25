import type { AlertOut, RuleOut } from '@vollab/api-types';
import {
  EMPTY,
  MAX_DECIMAL_RELATIVE,
  formatBusinessDays,
  formatDate,
  formatMoney,
  formatNumber,
  formatRelative,
} from '@/lib/format';
import { LIMIT_LABEL } from '@/lib/journal/labels';

/**
 * Alertas de gestão da operação (PRD 1.11 §5.10 e §8.1; BRD 1.8 RN-GES-01..07, RS-07, PRD-UI-10).
 * Tipo e estado sempre com texto, além da cor. Os números chegam no `details` com a unidade no nome
 * da chave (PRD §5.1); a formatação é sempre do `lib/format`.
 */

export type AlertKind = AlertOut['kind'];
export type AlertRule = AlertOut['rule'];
export type AlertState = AlertOut['state'];
export type RuleState = RuleOut['state'];

export const KIND_LABEL: Record<AlertKind, string> = {
  hedge: 'Hedge',
  exit: 'Saída',
  roll: 'Rolagem',
  limit: 'Limite',
  dividend: 'Provento',
};

export const RULE_LABEL: Record<AlertRule, string> = {
  hedge_band: 'Delta fora da banda',
  hedge_time: 'Tempo sem hedge',
  exit_edge: 'O edge acabou',
  exit_dte: 'Perto do vencimento',
  exit_profit: 'Meta de lucro',
  exit_stop: 'Stop',
  roll_suggested: 'Rolagem sugerida',
  limit_stress: 'Perda em stress acima do limite',
  limit_vega: 'Vega acima do limite',
  limit_underlying: 'Concentração por ativo',
  limit_expiry: 'Concentração por vencimento',
  dividend_upcoming: 'Data ex de provento',
  strike_adjustment_pending: 'Ajuste de strike sem lançamento',
};

export const ALERT_STATE_LABEL: Record<AlertState, string> = {
  active: 'Ativo',
  seen: 'Visto',
  resolved: 'Resolvido',
};

export const RULE_STATE_LABEL: Record<RuleState, string> = {
  ok: 'OK',
  triggered: 'Disparada',
  disabled: 'Desligada',
  unavailable: 'Indisponível',
};

export const RULE_HELP: Record<AlertRule, string> = {
  hedge_band:
    'Delta da última marcação fora da banda da simulação (0,10 ação por opção, não calibrada). O ajuste sugerido leva o delta só até a borda (H1).',
  hedge_time: 'Pregões desde o último hedge acima do intervalo configurado (desligado por padrão: com hedge diário, dispararia todo pregão).',
  exit_edge:
    'Edge relativo líquido da posição aberta, na direção dela, com a IV atual das pernas, a previsão até o vencimento e os custos de manter (hedge) e de fechar. Dispara com a estimativa pontual ≤ 0 (RN-GES-02).',
  exit_dte: 'Dias úteis até o vencimento mais próximo das pernas abertas no limite configurado (5 du, não calibrado).',
  exit_profit: 'P&L acumulado acima da fração configurada do P&L esperado na entrada. Desligada por padrão (regra G2).',
  exit_stop:
    'P&L acumulado abaixo da fração configurada da perda máxima do dimensionamento. Desligado por padrão: stop por P&L é má ideia (regra G2 da referência).',
  roll_suggested:
    'Mesma estrutura no 1º vencimento com ≥ 10 du, com edge líquido na direção da posição depois de somar o custo de fechar a atual (RN-GES-04). Nada é registrado sozinho.',
  limit_stress: 'Pior perda da carteira nos stresses acima da fração do capital (RF-RSK-04, não calibrado).',
  limit_vega: '|Vega| da carteira por ponto acima da fração do capital (RF-RSK-04, não calibrado).',
  limit_underlying: 'Perda em stress de um ativo acima da fração do orçamento de perda (não calibrado).',
  limit_expiry: 'Perda em stress de um vencimento acima da fração do orçamento de perda (não calibrado).',
  dividend_upcoming: 'Data ex de provento do ativo nos próximos 5 du com posição aberta (RS-07): confira o ajuste de strike das séries.',
  strike_adjustment_pending:
    'A B3 ajustou o strike de uma série da posição e não há lançamento de ajuste de strike depois da data (RN-DAD-03, RS-07).',
};

type Details = Record<string, unknown>;

function num(d: Details, key: string): number | null {
  const v = d[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function str(d: Details, key: string): string | null {
  const v = d[key];
  return typeof v === 'string' ? v : null;
}

/** Razão relativa com teto de exibição (limites muito estourados não derrubam a tela). */
export function relativeText(value: number | null): string {
  if (value == null) return EMPTY;
  if (Math.abs(value) > MAX_DECIMAL_RELATIVE) return `${value > 0 ? '>' : '<'} ${formatRelative(Math.sign(value) * MAX_DECIMAL_RELATIVE, 0)}`;
  return formatRelative(value);
}

/** Uma linha com os números do disparo, para a lista do painel e da operação. */
export function describeDetails(rule: AlertRule, details: Details): string {
  const d = details;
  switch (rule) {
    case 'hedge_band': {
      const adj = num(d, 'adjust_shares');
      return (
        `Δ ${formatNumber(num(d, 'delta_shares'), 1)} ações (banda ± ${formatNumber(num(d, 'half_width_shares'), 1)})` +
        (adj ? ` · ajuste até a borda: ${adj > 0 ? 'comprar' : 'vender'} ${formatNumber(Math.abs(adj))} ações` : '')
      );
    }
    case 'hedge_time':
      return `${formatBusinessDays(num(d, 'bd_since_last_hedge'))} sem hedge (intervalo ${formatBusinessDays(num(d, 'interval_bd'))})`;
    case 'exit_edge': {
      const lo = num(d, 'ci_low');
      const hi = num(d, 'ci_high');
      const v = num(d, 'net_relative_edge');
      return v == null
        ? 'Compra de vol: o hedge consome todo o edge restante'
        : `Edge relativo líquido ${relativeText(v)}` + (lo != null && hi != null ? ` [${relativeText(lo)}; ${relativeText(hi)}]` : '');
    }
    case 'exit_dte':
      return `${formatBusinessDays(num(d, 'days_to_expiry_bd'))} até o vencimento (limite ${formatBusinessDays(num(d, 'max_bd'))})`;
    case 'exit_profit':
      return `P&L ${formatMoney(str(d, 'pnl_brl'))} ≥ meta ${formatMoney(str(d, 'target_brl'))}`;
    case 'exit_stop':
      return `P&L ${formatMoney(str(d, 'pnl_brl'))} ≤ stop ${formatMoney(str(d, 'stop_brl'))}`;
    case 'roll_suggested': {
      const legs = Array.isArray(d.legs) ? (d.legs as { code?: string }[]).map((l) => l.code).join(' + ') : '';
      return (
        `Para ${formatDate(str(d, 'expiry'))} (${formatBusinessDays(num(d, 'horizon_bd'))})` +
        (legs ? ` · ${legs}` : '') +
        ` · edge relativo líquido ${relativeText(num(d, 'net_relative_edge'))} com o custo de fechar ${formatMoney(str(d, 'close_cost_brl'))}`
      );
    }
    case 'limit_stress':
    case 'limit_vega':
    case 'limit_underlying':
    case 'limit_expiry': {
      const name = str(d, 'limit') as keyof typeof LIMIT_LABEL | null;
      const scope = str(d, 'scope');
      return (
        `${name ? LIMIT_LABEL[name] : 'Limite'}${scope ? ` (${scope})` : ''}: ${relativeText(num(d, 'value'))}` +
        ` > ${relativeText(num(d, 'limit_value'))}`
      );
    }
    case 'dividend_upcoming': {
      const items = Array.isArray(d.items) ? (d.items as { amount_brl?: string; source?: string }[]) : [];
      const amounts = items.map((i) => `${formatMoney(i.amount_brl ?? null, 4)} (${i.source === 'manual' ? 'manual' : 'estimado'})`);
      return `Data ex em ${formatDate(str(d, 'ex_date'))}, em ${formatBusinessDays(num(d, 'days_to_ex_bd'))}` + (amounts.length ? ` · ${amounts.join(', ')}` : '');
    }
    case 'strike_adjustment_pending':
      return (
        `${str(d, 'code') ?? 'Série'}: strike ${formatMoney(str(d, 'old_strike_brl'))} → ${formatMoney(str(d, 'new_strike_brl'))}` +
        ` desde ${formatDate(str(d, 'effective_date'))}. Lance o ajuste de strike.`
      );
  }
}

/** Como `describeDetails`, mas um detalhe em formato inesperado não derruba a lista inteira. */
export function describeSafe(rule: AlertRule, details: Details): string {
  try {
    return describeDetails(rule, details);
  } catch {
    return 'Detalhe do alerta em formato inesperado.';
  }
}

/** O alerta usa algum parâmetro sem calibração por dados (rótulo "não calibrado"). */
export function uncalibrated(rule: AlertRule): boolean {
  return rule !== 'strike_adjustment_pending' && rule !== 'exit_edge' && rule !== 'roll_suggested';
}

/** Texto do estado de uma regra no painel "Gestão" da operação. */
export function ruleText(r: Pick<RuleOut, 'rule' | 'state' | 'reason' | 'details'>): string {
  if (r.state === 'disabled') return 'Desligada nas configurações.';
  if (r.state === 'unavailable') return r.reason ?? 'Sem insumos.';
  const details = r.details as Record<string, unknown>;
  if (r.rule === 'roll_suggested' && r.state !== 'triggered') {
    return r.reason ?? 'Rolagem avaliada: sem edge líquido na direção da posição.';
  }
  if (Object.keys(details).length === 0) return r.reason ?? EMPTY;
  return describeSafe(r.rule, details) + (r.reason && r.rule !== 'exit_edge' ? ` (${r.reason})` : '');
}
