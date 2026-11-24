import { z } from 'zod';
import type { PositionCreate, SimulationResponse, SizingOut, SizingRequest } from '@vollab/api-types';
import { marketInputToIso, parseMoneyInput } from '@/lib/format';
import { STRUCTURES, type StructureName } from './labels';

/**
 * Formulários do simulador (PRD 1.9 §5.8 e §8.1). O usuário digita dinheiro em BRL com vírgula e
 * data e hora no fuso da B3; a conversão para o contrato acontece só aqui (via `lib/format`). O
 * engine revalida tudo (o Pydantic é a autoridade, PRD §7).
 */

const money = (optional: boolean) =>
  z
    .string()
    .trim()
    .refine((v) => (optional && v === '') || parseMoneyInput(v) != null, 'Valor em R$ positivo (ex.: 1,80).');

const datetime = z.string().refine((v) => marketInputToIso(v) != null, 'Data e hora inválidas.');
const seriesId = z.string().regex(/^\d+$/, 'Escolha a série.');

export const simulatorSchema = z
  .object({
    structure: z.enum(STRUCTURES.map((s) => s.name) as [StructureName, ...StructureName[]]),
    call: seriesId,
    put: z.string(),
    manualSpot: money(true),
    manualCall: money(true),
    manualPut: money(true),
    manualAt: datetime,
    capital: money(true),
    marginPerLot: money(true),
    lots: z.string().regex(/^[1-9]\d{0,4}$/, 'Lotes: inteiro de 1 a 99.999.'),
  })
  .superRefine((v, ctx) => {
    if (needsPut(v.structure) && !/^\d+$/.test(v.put)) {
      ctx.addIssue({ code: 'custom', path: ['put'], message: 'Escolha a put.' });
    }
  });

export type SimulatorValues = z.infer<typeof simulatorSchema>;

export function needsPut(structure: StructureName): boolean {
  return STRUCTURES.find((s) => s.name === structure)?.legs === 'call_put';
}

/** Monta o pedido de `/sizing` (mesmos insumos de `/simulations`, mais capital e margem). */
export function toSizingRequest(ticker: string, v: SimulatorValues): SizingRequest {
  const at = marketInputToIso(v.manualAt) as string;
  const leg = (id: string, manual: string) => {
    const price = manual ? parseMoneyInput(manual) : null;
    return price ? { series_id: Number(id), manual_price_brl: price, manual_price_at: at } : { series_id: Number(id) };
  };
  const legs = [leg(v.call, v.manualCall)];
  if (needsPut(v.structure)) legs.push(leg(v.put, v.manualPut));
  const spot = v.manualSpot ? parseMoneyInput(v.manualSpot) : null;
  const capital = v.capital ? parseMoneyInput(v.capital) : null;
  const margin = v.marginPerLot ? parseMoneyInput(v.marginPerLot) : null;
  return {
    ticker,
    structure: v.structure,
    legs,
    lots: Number(v.lots),
    ...(spot ? { manual_spot_brl: spot, manual_spot_at: at } : {}),
    ...(capital ? { capital_brl: capital } : {}),
    ...(margin ? { margin_per_lot_brl: margin, margin_at: at } : {}),
  };
}

/**
 * Motivos que exigem justificativa no registro (mesma regra do engine): fora de "edge líquido" na
 * direção da estrutura, ou lotes acima do sugerido.
 */
export function overrideReasons(sim: SimulationResponse, sizing: SizingOut, lots: number): string[] {
  const out: string[] = [];
  if (sim.state !== 'edge') out.push(`semáforo em ${sim.state}`);
  else if (!sim.direction_match) out.push('direção da estrutura oposta à do sinal');
  if (lots > sizing.n_final) out.push(`${lots} lote(s) acima do sugerido (${sizing.n_final})`);
  return out;
}

export const entrySchema = z.object({
  lots: z.string().regex(/^[1-9]\d{0,4}$/, 'Lotes: inteiro de 1 a 99.999.'),
  prices: z.array(money(false)),
  fees: z.array(money(true)),
  stockPrice: money(true),
  executedAt: datetime,
  note: z.string().max(2000),
  overrideReason: z.string().max(2000),
});

export type EntryValues = z.infer<typeof entrySchema>;

/** Monta o registro da entrada. O engine recalcula tudo; aqui só vão insumos e o executado. */
export function toPositionCreate(
  request: SizingRequest,
  sim: SimulationResponse,
  v: EntryValues,
): PositionCreate {
  const lots = Number(v.lots);
  const stock =
    sim.stock != null
      ? {
          quantity: sim.stock.quantity_per_lot * lots,
          price_brl: parseMoneyInput(v.stockPrice) ?? sim.stock.price_brl,
        }
      : undefined;
  return {
    ...request,
    lots,
    base_config_version_id: sim.config_version_id,
    executed_legs: sim.legs.map((leg, i) => ({
      series_id: leg.series_id,
      price_brl: parseMoneyInput(v.prices[i] ?? '') ?? leg.price_brl,
      fees_brl: (v.fees[i] ? parseMoneyInput(v.fees[i]) : null) ?? '0',
    })),
    ...(stock ? { stock } : {}),
    executed_at: marketInputToIso(v.executedAt) as string,
    ...(v.note.trim() ? { note: v.note.trim() } : {}),
    ...(v.overrideReason.trim() ? { override_reason: v.overrideReason.trim() } : {}),
  };
}
