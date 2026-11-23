import { z } from 'zod';
import type { EventCreate } from '@vollab/api-types';
import { zEventCreate } from '@vollab/api-types/zod';

/**
 * Formulário de evento (RF-EVT-01/02). Os campos chegam como texto; a regra do engine é repetida
 * aqui só para resposta rápida (o Pydantic continua sendo a autoridade, PRD §7).
 */
export const eventFormSchema = z
  .object({
    kind: zEventCreate.shape.kind,
    ticker: z.string().trim().toUpperCase(),
    event_date: z.iso.date({ error: 'Informe a data.' }),
    status: zEventCreate.shape.status,
    amount: z.string().trim(),
    note: z.string().trim().max(500),
  })
  .superRefine((v, ctx) => {
    const withAmount = v.kind === 'ex_dividend' || v.kind === 'ex_jcp';
    const marketWide = v.kind === 'copom' || v.kind === 'macro';
    if (!marketWide && !/^[A-Z0-9]{4,12}$/.test(v.ticker)) {
      ctx.addIssue({ code: 'custom', path: ['ticker'], message: 'Escolha o ativo.' });
    }
    if (withAmount && parseAmount(v.amount) == null) {
      ctx.addIssue({ code: 'custom', path: ['amount'], message: 'Valor por ação maior que zero (ex.: 0,85).' });
    }
  });

export type EventFormValues = z.input<typeof eventFormSchema>;

/** "0,85" ou "0.85" → "0.85" (decimal exato, como a API espera). Inválido → null. */
export function parseAmount(raw: string): string | null {
  const normalized = raw.trim().replace(',', '.');
  if (!/^\d+(\.\d{1,6})?$/.test(normalized) || Number(normalized) <= 0) return null;
  return normalized;
}

export function toEventCreate(v: EventFormValues): EventCreate {
  const withAmount = v.kind === 'ex_dividend' || v.kind === 'ex_jcp';
  const marketWide = v.kind === 'copom' || v.kind === 'macro';
  return zEventCreate.parse({
    kind: v.kind,
    ticker: marketWide ? null : v.ticker.trim().toUpperCase(),
    event_date: v.event_date,
    status: v.status,
    amount: withAmount ? parseAmount(v.amount) : null,
    note: v.note.trim() || null,
  });
}
