import { z } from 'zod';
import type { ConfigParamsInput, ConfigParamsOutput } from '@vollab/api-types';
import {
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
  block: 'costs' | 'edge' | 'vol' | 'forecast';
  key: string;
  label: string;
  unit: Unit;
  min: number;
  max: number;
  help?: string;
  /** Vale só no próximo recálculo do worker (o histórico gravado não é refeito em silêncio). */
  nextRecompute?: boolean;
  /** Valor a conferir na tabela vigente da B3. */
  verify?: boolean;
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
} as const satisfies Record<string, FieldSpec>;

export type FieldName = keyof typeof FIELDS;
export const FIELD_NAMES = Object.keys(FIELDS) as FieldName[];
export const BLOCK_LABEL = { costs: 'Custos', edge: 'Edge', vol: 'Volatilidade', forecast: 'Previsão' } as const;

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
    note: z.string().trim().min(1, 'Diga o que mudou e por quê.').max(500),
  })
  .superRefine((v, ctx) => {
    for (const name of FIELD_NAMES) {
      const spec: FieldSpec = FIELDS[name];
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
  });

export type ConfigFormValues = z.input<typeof configFormSchema>;

type Block = Record<string, unknown>;

function block(params: ConfigParamsOutput, name: FieldSpec['block']): Block {
  return (params[name] ?? {}) as Block;
}

export function toFormValues(params: ConfigParamsOutput): ConfigFormValues {
  const out: Record<string, string> = { note: '' };
  for (const name of FIELD_NAMES) {
    const spec: FieldSpec = FIELDS[name];
    out[name] = toInput(spec.unit, Number(block(params, spec.block)[spec.key]));
  }
  const bands = (params.costs?.moneyness_bands ?? [0.95, 1.05]) as [number, number];
  out.band_low = toPlainInput(bands[0]);
  out.band_high = toPlainInput(bands[1]);
  return out as ConfigFormValues;
}

/** Snapshot inteiro para o `POST /config`: o vigente com os campos do formulário trocados. */
export function toConfigParams(values: ConfigFormValues, current: ConfigParamsOutput): ConfigParamsInput {
  const next = structuredClone(current) as Record<string, Block>;
  for (const name of FIELD_NAMES) {
    const spec: FieldSpec = FIELDS[name];
    const value = parse(spec.unit, values[name]);
    if (value == null) throw new RangeError(`Campo inválido: ${name}.`);
    next[spec.block] = { ...(next[spec.block] ?? {}), [spec.key]: value };
  }
  next.costs = {
    ...next.costs,
    moneyness_bands: [parsePlainInput(values.band_low), parsePlainInput(values.band_high)],
  };
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
