import type { PositionOut, RollFrom } from '@vollab/api-types';
import { parseMoneyInput, parseMoneyOrZeroInput, toMoneyInput } from '@/lib/format';

/**
 * Rolagem (PRD 1.10 §5.9 e 1.11 §5.10; RN-GES-04): fechamento das pernas de opção em aberto da
 * operação de origem, gravado junto com a nova entrada (`roll_from` do `POST /positions`).
 */

export interface OpenLeg {
  instrument: string;
  series_id: number;
  quantity: number;
  /** Preço da última marcação D-1 (sugestão editável). */
  lastPrice: string | null;
}

/** Pernas de opção com quantidade em aberto (o hedge em ações não é rolado). */
export function openOptionLegs(origin: PositionOut): OpenLeg[] {
  const last = origin.marks.at(-1);
  return origin.holdings
    .filter((h) => h.series_id != null && h.quantity !== 0)
    .map((h) => ({
      instrument: h.instrument,
      series_id: h.series_id as number,
      quantity: h.quantity,
      lastPrice: last?.legs.find((l) => l.code === h.instrument)?.price_brl ?? null,
    }));
}

export function defaultClosePrices(legs: OpenLeg[]): string[] {
  return legs.map((l) => (l.lastPrice != null ? toMoneyInput(l.lastPrice) : ''));
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Link do simulador em modo rolagem, com a query codificada; null se o vencimento não for uma data
 * ISO (o dado vem do engine, mas o link nunca injeta parâmetros; revisão de segurança, M-3).
 */
export function rollHref(ticker: string | null, positionId: number, expiry: unknown, structure: string | null): string | null {
  if (typeof expiry !== 'string' || !ISO_DATE.test(expiry)) return null;
  const q = new URLSearchParams({ roll_from: String(positionId), expiry });
  if (ticker) q.set('ticker', ticker);
  if (structure) q.set('structure', structure);
  return `/app/simulador?${q.toString()}`;
}

/** Monta `roll_from`: cada perna sai inteira (quantidade com o sinal contrário ao em aberto). */
export function toRollFrom(positionId: number, legs: OpenLeg[], prices: string[], fees: string[]): RollFrom {
  return {
    position_id: positionId,
    legs: legs.map((l, i) => ({
      instrument: l.instrument,
      quantity: -l.quantity,
      price_brl: parseMoneyOrZeroInput(prices[i] ?? '') ?? '0',
      fees_brl: (fees[i] ? parseMoneyInput(fees[i]) : null) ?? '0',
    })),
  };
}
