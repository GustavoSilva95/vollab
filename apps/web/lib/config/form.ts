import { z } from 'zod';
import type { ConfigParamsInput, ConfigParamsOutput } from '@vollab/api-types';
import {
  parseMoneyInput,
  parsePercentInput,
  parsePlainInput,
  parseVolPointsInput,
  toPercentInput,
  toPlainInput,
  toVolPointsInput,
} from '@/lib/format';

/**
 * Formulário da configuração versionada (PRD 1.8 §8.1; RN-CST-02, RN-EDG-05/07, QA-11). Os campos
 * chegam como texto, na unidade em que o usuário lê (% ou pontos de vol); a conversão para decimal é
 * do `lib/format`. As faixas repetem as do engine só para resposta rápida: o Pydantic é a autoridade
 * (PRD §7) e o 422 aparece na tela.
 */

type Unit = 'percent' | 'points' | 'plain' | 'int';

interface FieldSpec {
  block: 'costs' | 'edge' | 'vol' | 'forecast' | 'risk' | 'journal' | 'management';
  /** Caminho dentro do bloco; `limits.x` para campos aninhados. */
  key: string;
  /** Valor padrão sem calibração por dados (rótulo "não calibrado"). */
  uncalibrated?: boolean;
  label: string;
  unit: Unit;
  min: number;
  max: number;
  help?: string;
  /** Vale só no próximo recálculo do worker (o histórico gravado não é refeito em silêncio). */
  nextRecompute?: boolean;
  /** Valor a conferir na tabela vigente da B3. */
  verify?: boolean;
  /** Vazio = regra desligada (`null` no engine, PRD 1.11 §5.10). */
  optional?: boolean;
  /** Aviso fixo junto do campo (ex.: regra G2 no stop). */
  warning?: string;
}

export const FIELDS = {
  option_fee_rate: {
    block: 'costs',
    key: 'option_fee_rate',
    label: 'Taxas B3 em opções (%)',
    unit: 'percent',
    min: 0,
    max: 0.01,
    help: 'Pessoa física: negociação 0,0370% + liquidação 0,0275% + registro 0,0695%.',
    verify: true,
  },
  underlying_fee_rate: {
    block: 'costs',
    key: 'underlying_fee_rate',
    label: 'Taxas B3 em ações, hedge (%)',
    unit: 'percent',
    min: 0,
    max: 0.01,
    verify: true,
  },
  brokerage_per_order_brl: {
    block: 'costs',
    key: 'brokerage_per_order_brl',
    label: 'Corretagem por ordem (R$)',
    unit: 'plain',
    min: 0,
    max: 1000,
  },
  brokerage_rate: { block: 'costs', key: 'brokerage_rate', label: 'Corretagem sobre o volume (%)', unit: 'percent', min: 0, max: 0.05 },
  reference_contracts: {
    block: 'costs',
    key: 'reference_contracts',
    label: 'Opções por perna na estrutura de referência',
    unit: 'int',
    min: 1,
    max: 1_000_000,
    help: 'Rateia a corretagem fixa (4 ordens) por straddle.',
  },
  hedge_interval_bd: {
    block: 'costs',
    key: 'hedge_interval_bd',
    label: 'Intervalo do hedge no custo (du)',
    unit: 'int',
    min: 1,
    max: 21,
    help: 'Leland: hedge mais espaçado custa menos e protege menos.',
  },
  tick_brl: {
    block: 'costs',
    key: 'tick_brl',
    label: 'Piso do spread, tick (R$)',
    unit: 'plain',
    min: 0.0001,
    max: 1,
    nextRecompute: true,
  },
  spread_min_trades: {
    block: 'costs',
    key: 'spread_min_trades',
    label: 'Negócios mínimos da série para medir spread',
    unit: 'int',
    min: 2,
    max: 10_000,
    nextRecompute: true,
  },
  spread_lookback_bd: {
    block: 'costs',
    key: 'spread_lookback_bd',
    label: 'Pregões da estimativa de spread',
    unit: 'int',
    min: 1,
    max: 63,
  },
  normal_spread_default: {
    block: 'edge',
    key: 'normal_spread_default',
    label: 'Spread normal não calibrado (%)',
    unit: 'percent',
    min: -0.5,
    max: 2,
    help: 'Vale até haver 8 janelas de IV de prazo constante (QA-14). Nunca zero implícito.',
  },
  threshold_vol_pts: {
    block: 'edge',
    key: 'threshold_vol_pts',
    label: 'Limiar de edge (pontos de vol)',
    unit: 'points',
    min: 0,
    max: 0.2,
    help: 'Somado aos custos no semáforo; não calibrado até a Etapa 9 (RN-EDG-05).',
  },
  iv_rank_min_days: { block: 'edge', key: 'iv_rank_min_days', label: 'Pregões mínimos do IV rank', unit: 'int', min: 20, max: 252 },
  constant_maturity_bd: {
    block: 'vol',
    key: 'constant_maturity_bd',
    label: 'Prazo constante da IV (du)',
    unit: 'int',
    min: 5,
    max: 252,
    nextRecompute: true,
  },
  ci_level: { block: 'vol', key: 'ci_level', label: 'Nível dos intervalos (%)', unit: 'percent', min: 0.51, max: 0.99 },
  ewma_lambda: {
    block: 'forecast',
    key: 'ewma_lambda',
    label: 'λ da EWMA',
    unit: 'plain',
    min: 0.9,
    max: 0.99,
    nextRecompute: true,
  },
  stress_gap: {
    block: 'risk',
    key: 'stress_gap',
    label: 'Gap do ativo nos stresses (±%)',
    unit: 'percent',
    min: 0.01,
    max: 0.5,
    help: 'Stresses simples da carteira e do teto do dimensionamento (RF-RSK-03).',
  },
  stress_vol_pts: { block: 'risk', key: 'stress_vol_pts', label: 'Choque de vol nos stresses (pontos)', unit: 'points', min: 0.01, max: 1 },
  crisis_horizon_bd: {
    block: 'risk',
    key: 'crisis_horizon_bd',
    label: 'Pregões da pior janela da crise',
    unit: 'int',
    min: 1,
    max: 20,
    help: 'QA-12: pior retorno acumulado nesse número de pregões dentro do episódio. Vale na próxima medição.',
  },
  max_stress_loss_fraction: {
    block: 'risk',
    key: 'limits.max_stress_loss_fraction',
    label: 'Limite: pior perda em stress (% do capital)',
    unit: 'percent',
    min: 0.01,
    max: 1,
    uncalibrated: true,
  },
  max_abs_vega_fraction: {
    block: 'risk',
    key: 'limits.max_abs_vega_fraction',
    label: 'Limite: |vega| por ponto (% do capital)',
    unit: 'percent',
    min: 0.0001,
    max: 1,
    uncalibrated: true,
  },
  max_underlying_share: {
    block: 'risk',
    key: 'limits.max_underlying_share',
    label: 'Limite: perda de um ativo (% do orçamento de perda)',
    unit: 'percent',
    min: 0.01,
    max: 1,
    uncalibrated: true,
  },
  max_expiry_share: {
    block: 'risk',
    key: 'limits.max_expiry_share',
    label: 'Limite: perda de um vencimento (% do orçamento de perda)',
    unit: 'percent',
    min: 0.01,
    max: 1,
    uncalibrated: true,
  },
  residual_max_ratio: {
    block: 'journal',
    key: 'residual_max_ratio',
    label: 'Meta do resíduo da atribuição, CS-04 (%)',
    unit: 'percent',
    min: 0.01,
    max: 1,
  },
  residual_min_brl: {
    block: 'journal',
    key: 'residual_min_brl',
    label: 'Resíduo mínimo para o sinal de erro (R$)',
    unit: 'plain',
    min: 0,
    max: 1_000_000_000,
    uncalibrated: true,
    help: 'Evita acusar erro de lançamento em dias parados (RS-06).',
  },
  // Gestão da operação (PRD 1.11 §5.10; QA-11, decisões do usuário em 2026-11-24).
  exit_dte_bd: {
    block: 'management',
    key: 'exit_dte_bd',
    label: 'Saída: alerta com até N du até o vencimento',
    unit: 'int',
    min: 0,
    max: 63,
    optional: true,
    uncalibrated: true,
    help: 'Vazio desliga o alerta de prazo.',
  },
  hedge_alert_interval_bd: {
    block: 'management',
    key: 'hedge_interval_bd',
    label: 'Hedge: alerta depois de N pregões sem hedge',
    unit: 'int',
    min: 1,
    max: 63,
    optional: true,
    uncalibrated: true,
    help: 'Desligado por padrão (vazio): com hedge diário dispararia todo pregão. A banda de delta é a da simulação.',
  },
  profit_target_fraction: {
    block: 'management',
    key: 'profit_target_fraction',
    label: 'Saída: meta de lucro (% do P&L esperado na entrada)',
    unit: 'percent',
    min: 0.01,
    max: 5,
    optional: true,
    uncalibrated: true,
    help: 'Vazio = desligada (padrão).',
  },
  stop_loss_fraction: {
    block: 'management',
    key: 'stop_loss_fraction',
    label: 'Saída: stop (% da perda máxima do dimensionamento)',
    unit: 'percent',
    min: 0.01,
    max: 5,
    optional: true,
    uncalibrated: true,
    warning: 'Stop por P&L é má ideia (regra G2 da referência): saia quando o edge acabar ou a previsão mudar.',
    help: 'Vazio = desligado (padrão).',
  },
  roll_min_dte_bd: {
    block: 'management',
    key: 'roll_min_dte_bd',
    label: 'Rolagem: destino no 1º vencimento com ≥ N du',
    unit: 'int',
    min: 1,
    max: 126,
    uncalibrated: true,
  },
  dividend_lead_bd: {
    block: 'management',
    key: 'dividend_lead_bd',
    label: 'Proventos: alerta com N du de antecedência da data ex',
    unit: 'int',
    min: 0,
    max: 63,
    uncalibrated: true,
    help: '0 desliga o alerta de data ex (o de ajuste de strike sem lançamento continua).',
  },
} as const satisfies Record<string, FieldSpec>;

export type FieldName = keyof typeof FIELDS;
export const FIELD_NAMES = Object.keys(FIELDS) as FieldName[];
export const BLOCK_LABEL = {
  costs: 'Custos',
  edge: 'Edge',
  vol: 'Volatilidade',
  forecast: 'Previsão',
  risk: 'Risco e limites',
  journal: 'Diário',
  management: 'Gestão da operação',
} as const;

function parse(unit: Unit, raw: string): number | null {
  if (unit === 'percent') return parsePercentInput(raw);
  if (unit === 'points') return parseVolPointsInput(raw);
  const value = parsePlainInput(raw);
  if (value == null) return null;
  return unit === 'int' && !Number.isInteger(value) ? null : value;
}

function toInput(unit: Unit, value: number): string {
  if (unit === 'percent') return toPercentInput(value);
  if (unit === 'points') return toVolPointsInput(value);
  return toPlainInput(value);
}

function rangeMessage(spec: FieldSpec): string {
  return `Entre ${toInput(spec.unit, spec.min)} e ${toInput(spec.unit, spec.max)}.`;
}

export const configFormSchema = z
  .object({
    ...(Object.fromEntries(FIELD_NAMES.map((n) => [n, z.string()])) as Record<FieldName, z.ZodString>),
    band_low: z.string(),
    band_high: z.string(),
    capital: z.string(),
    note: z.string().trim().min(1, 'Diga o que mudou e por quê.').max(500),
  })
  .superRefine((v, ctx) => {
    for (const name of FIELD_NAMES) {
      const spec: FieldSpec = FIELDS[name];
      if (spec.optional && v[name].trim() === '') continue;
      const value = parse(spec.unit, v[name]);
      if (value == null || value < spec.min || value > spec.max) {
        ctx.addIssue({ code: 'custom', path: [name], message: rangeMessage(spec) });
      }
    }
    const lo = parsePlainInput(v.band_low);
    const hi = parsePlainInput(v.band_high);
    if (lo == null || hi == null || !(lo >= 0.5 && lo < 1 && hi > 1 && hi <= 1.5)) {
      ctx.addIssue({ code: 'custom', path: ['band_high'], message: '0,5 ≤ inferior < 1 < superior ≤ 1,5.' });
    }
    if (v.capital.trim() !== '' && parseMoneyInput(v.capital) == null) {
      ctx.addIssue({ code: 'custom', path: ['capital'], message: 'Capital em R$ (ou vazio para não informar).' });
    }
  });

export type ConfigFormValues = z.input<typeof configFormSchema>;

type Block = Record<string, unknown>;

function block(params: ConfigParamsOutput, name: FieldSpec['block']): Block {
  return (params[name] ?? {}) as Block;
}

function getPath(obj: Block, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, k) => (acc as Block | undefined)?.[k], obj);
}

function setPath(obj: Block, path: string, value: unknown): Block {
  const [head, ...rest] = path.split('.') as [string, ...string[]];
  if (rest.length === 0) return { ...obj, [head]: value };
  return { ...obj, [head]: setPath((obj[head] ?? {}) as Block, rest.join('.'), value) };
}

export function toFormValues(params: ConfigParamsOutput): ConfigFormValues {
  const out: Record<string, string> = { note: '' };
  for (const name of FIELD_NAMES) {
    const spec: FieldSpec = FIELDS[name];
    const raw = getPath(block(params, spec.block), spec.key);
    out[name] = raw == null && spec.optional ? '' : toInput(spec.unit, Number(raw));
  }
  const bands = (params.costs?.moneyness_bands ?? [0.95, 1.05]) as [number, number];
  out.band_low = toPlainInput(bands[0]);
  out.band_high = toPlainInput(bands[1]);
  const capital = params.sizing?.capital_brl;
  out.capital = capital == null ? '' : toPlainInput(capital);
  return out as ConfigFormValues;
}

/** Snapshot inteiro para o `POST /config`: o vigente com os campos do formulário trocados. */
export function toConfigParams(values: ConfigFormValues, current: ConfigParamsOutput): ConfigParamsInput {
  const next = structuredClone(current) as Record<string, Block>;
  for (const name of FIELD_NAMES) {
    const spec: FieldSpec = FIELDS[name];
    if (spec.optional && values[name].trim() === '') {
      next[spec.block] = setPath(next[spec.block] ?? {}, spec.key, null);
      continue;
    }
    const value = parse(spec.unit, values[name]);
    if (value == null) throw new RangeError(`Campo inválido: ${name}.`);
    next[spec.block] = setPath(next[spec.block] ?? {}, spec.key, value);
  }
  next.costs = {
    ...next.costs,
    moneyness_bands: [parsePlainInput(values.band_low), parsePlainInput(values.band_high)],
  };
  const capital = values.capital.trim() === '' ? null : Number(parseMoneyInput(values.capital));
  next.sizing = { ...next.sizing, capital_brl: capital };
  return next as ConfigParamsInput;
}

export interface ParamChange {
  path: string;
  before: string;
  after: string;
}

function flatten(value: unknown, prefix: string, out: Map<string, string>): void {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      flatten(v, prefix ? `${prefix}.${k}` : k, out);
    }
    return;
  }
  out.set(prefix, JSON.stringify(value));
}

/** Diferenças entre duas versões (caminho → antes, depois), em ordem alfabética. */
export function diffParams(before: unknown, after: unknown): ParamChange[] {
  const a = new Map<string, string>();
  const b = new Map<string, string>();
  flatten(before, '', a);
  flatten(after, '', b);
  const keys = [...new Set([...a.keys(), ...b.keys()])].sort();
  return keys
    .filter((k) => a.get(k) !== b.get(k))
    .map((k) => ({ path: k, before: a.get(k) ?? '—', after: b.get(k) ?? '—' }));
}
