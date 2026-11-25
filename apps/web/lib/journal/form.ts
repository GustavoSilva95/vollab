import { z } from 'zod';
import type { EntryCreate, EntryOut, HoldingOut } from '@vollab/api-types';
import { marketInputToIso, parseMoneyInput, parseMoneyOrZeroInput } from '@/lib/format';

/**
 * Formulário de lançamento (PRD 1.10 §5.9; RF-DIA-02/03, RS-06). O usuário digita dinheiro com
 * vírgula e data e hora no fuso da B3; a conversão para o contrato é feita pelo `lib/format`. As
 * regras de consistência (sinal, perna comprada ou vendida, vencimento) são do engine: o 422 aparece
 * na tela com o motivo.
 */

export const USER_KINDS = ['hedge', 'exit', 'exercise', 'assignment', 'strike_adjustment', 'void'] as const;
export type UserKind = (typeof USER_KINDS)[number];

const QTY = /^-?[1-9]\d{0,7}$/;
const datetime = z.string().refine((v) => marketInputToIso(v) != null, 'Data e hora inválidas.');

export const entryFormSchema = z
  .object({
    kind: z.enum(USER_KINDS),
    instrument: z.string(),
    quantity: z.string().trim(),
    price: z.string().trim(),
    fees: z.string().trim(),
    strikeAfter: z.string().trim(),
    linkedEntryId: z.string(),
    voidReason: z.string().trim().max(2000),
    executedAt: datetime,
    note: z.string().max(2000),
  })
  .superRefine((v, ctx) => {
    if (v.kind === 'void') {
      if (!/^\d+$/.test(v.linkedEntryId)) ctx.addIssue({ code: 'custom', path: ['linkedEntryId'], message: 'Escolha o lançamento.' });
      if (v.voidReason.length < 10) {
        ctx.addIssue({ code: 'custom', path: ['voidReason'], message: 'Motivo do estorno (mín. 10 caracteres).' });
      }
      return;
    }
    if (!v.instrument) ctx.addIssue({ code: 'custom', path: ['instrument'], message: 'Escolha o instrumento.' });
    if (!QTY.test(v.quantity)) {
      ctx.addIssue({ code: 'custom', path: ['quantity'], message: 'Inteiro com sinal (+ compra, − venda), ex.: -100.' });
    }
    if (parseMoneyOrZeroInput(v.price) == null) {
      ctx.addIssue({ code: 'custom', path: ['price'], message: 'Valor em R$ (ex.: 1,80; zero se venceu sem valor).' });
    }
    if (v.fees && parseMoneyInput(v.fees) == null && parseMoneyOrZeroInput(v.fees) !== '0') {
      ctx.addIssue({ code: 'custom', path: ['fees'], message: 'Valor em R$.' });
    }
    if (v.kind === 'strike_adjustment' && parseMoneyInput(v.strikeAfter) == null) {
      ctx.addIssue({ code: 'custom', path: ['strikeAfter'], message: 'Novo strike efetivo em R$.' });
    }
  });

export type EntryFormValues = z.infer<typeof entryFormSchema>;

/** Monta o `POST /positions/{id}/entries`. */
export function toEntryCreate(v: EntryFormValues): EntryCreate {
  const executed_at = marketInputToIso(v.executedAt) as string;
  const note = v.note.trim() ? { note: v.note.trim() } : {};
  if (v.kind === 'void') {
    return { kind: 'void', executed_at, linked_entry_id: Number(v.linkedEntryId), void_reason: v.voidReason, ...note };
  }
  return {
    kind: v.kind,
    executed_at,
    instrument: v.instrument,
    quantity: Number(v.quantity),
    price_brl: parseMoneyOrZeroInput(v.price) as string,
    fees_brl: (v.fees ? parseMoneyOrZeroInput(v.fees) : null) ?? '0',
    ...(v.kind === 'strike_adjustment' ? { strike_after_brl: parseMoneyInput(v.strikeAfter) as string } : {}),
    ...note,
  };
}

/** Lançamentos que ainda podem ser estornados (não a entrada, não estornos, não os já anulados). */
export function voidable(entries: readonly EntryOut[]): EntryOut[] {
  return entries.filter((e) => e.kind !== 'entry' && e.kind !== 'void' && e.voided_by == null);
}

/** Instrumentos válidos por tipo (o engine confere de novo). */
export function instrumentsFor(kind: UserKind, ticker: string, holdings: readonly HoldingOut[]): string[] {
  const options = holdings.filter((h) => h.series_id != null);
  if (kind === 'hedge') return [ticker];
  if (kind === 'exit') return holdings.filter((h) => h.quantity !== 0).map((h) => h.instrument);
  if (kind === 'exercise') return options.filter((h) => h.quantity > 0).map((h) => h.instrument);
  if (kind === 'assignment') return options.filter((h) => h.quantity < 0).map((h) => h.instrument);
  if (kind === 'strike_adjustment') return options.filter((h) => h.quantity !== 0).map((h) => h.instrument);
  return [];
}
