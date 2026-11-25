import { describe, expect, it } from 'vitest';
import type { EntryOut } from '@vollab/api-types';
import { entryFormSchema, instrumentsFor, toEntryCreate, voidable, type EntryFormValues } from './form';

const base: EntryFormValues = {
  kind: 'hedge',
  instrument: 'PETR4',
  quantity: '-30',
  price: '43,50',
  fees: '0,39',
  strikeAfter: '',
  linkedEntryId: '',
  voidReason: '',
  executedAt: '2026-11-18T14:00',
  note: '',
};

describe('formulário de lançamento (PRD 1.10 §5.9)', () => {
  it('hedge: quantidade com sinal, dinheiro decimal e hora de Brasília', () => {
    expect(entryFormSchema.safeParse(base).success).toBe(true);
    expect(toEntryCreate(base)).toEqual({
      kind: 'hedge',
      executed_at: '2026-11-18T14:00:00-03:00',
      instrument: 'PETR4',
      quantity: -30,
      price_brl: '43.50',
      fees_brl: '0.39',
    });
  });

  it('saída a R$ 0 é aceita (opção que venceu sem valor)', () => {
    const v = { ...base, kind: 'exit' as const, instrument: 'PETRX44', quantity: '100', price: '0', fees: '' };
    expect(entryFormSchema.safeParse(v).success).toBe(true);
    expect(toEntryCreate(v)).toMatchObject({ price_brl: '0', fees_brl: '0' });
  });

  it('estorno exige o lançamento e o motivo; só manda o que o engine pede', () => {
    const v = { ...base, kind: 'void' as const, linkedEntryId: '', voidReason: 'curto' };
    const r = entryFormSchema.safeParse(v);
    expect(r.success).toBe(false);
    const ok = { ...v, linkedEntryId: '7', voidReason: 'hedge lançado em dobro' };
    expect(toEntryCreate(ok)).toEqual({
      kind: 'void',
      executed_at: '2026-11-18T14:00:00-03:00',
      linked_entry_id: 7,
      void_reason: 'hedge lançado em dobro',
    });
  });

  it('ajuste de strike exige o novo strike; quantidade zero ou sem sinal válido é recusada', () => {
    const v = { ...base, kind: 'strike_adjustment' as const, instrument: 'PETRL44', quantity: '-110', price: '0' };
    expect(entryFormSchema.safeParse(v).success).toBe(false);
    expect(toEntryCreate({ ...v, strikeAfter: '33,20' })).toMatchObject({ strike_after_brl: '33.20', quantity: -110 });
    expect(entryFormSchema.safeParse({ ...base, quantity: '0' }).success).toBe(false);
    expect(entryFormSchema.safeParse({ ...base, quantity: '1.5' }).success).toBe(false);
  });

  it('instrumentos elegíveis por tipo e lançamentos estornáveis', () => {
    const holdings = [
      { instrument: 'PETR4', series_id: null, quantity: 30 },
      { instrument: 'PETRL44', series_id: 1, quantity: -100 },
      { instrument: 'PETRX44', series_id: 2, quantity: 100 },
      { instrument: 'PETRA1', series_id: 3, quantity: 0 },
    ];
    expect(instrumentsFor('hedge', 'PETR4', holdings)).toEqual(['PETR4']);
    expect(instrumentsFor('exit', 'PETR4', holdings)).toEqual(['PETR4', 'PETRL44', 'PETRX44']);
    expect(instrumentsFor('exercise', 'PETR4', holdings)).toEqual(['PETRX44']);
    expect(instrumentsFor('assignment', 'PETR4', holdings)).toEqual(['PETRL44']);
    const e = (id: number, kind: EntryOut['kind'], voided_by: number | null = null): EntryOut => ({
      id,
      kind,
      instrument: 'PETR4',
      series_id: null,
      quantity: 1,
      price_brl: '1.00',
      fees_brl: '0.00',
      brokerage_brl: '0.00',
      executed_at: '2026-11-18T17:00:00Z',
      linked_entry_id: null,
      strike_after_brl: null,
      void_reason: null,
      note: null,
      voided_by,
    });
    expect(voidable([e(1, 'entry'), e(2, 'hedge', 4), e(3, 'hedge'), e(4, 'void')]).map((x) => x.id)).toEqual([3]);
  });
});
