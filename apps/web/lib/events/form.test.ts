import { describe, expect, it } from 'vitest';
import { eventFormSchema, parseAmount, toEventCreate } from './form';

const base = { kind: 'earnings', ticker: 'petr4', event_date: '2026-12-10', status: 'estimated', amount: '', note: '' } as const;

describe('formulário de evento', () => {
  it('aceita resultado com ativo e normaliza o ticker', () => {
    const parsed = eventFormSchema.parse(base);
    expect(toEventCreate(parsed)).toEqual({
      kind: 'earnings',
      ticker: 'PETR4',
      event_date: '2026-12-10',
      status: 'estimated',
      amount: null,
      note: null,
    });
  });

  it('ex-dividendo exige valor; aceita vírgula decimal', () => {
    expect(eventFormSchema.safeParse({ ...base, kind: 'ex_dividend' }).success).toBe(false);
    const ok = eventFormSchema.parse({ ...base, kind: 'ex_dividend', amount: '0,85' });
    expect(toEventCreate(ok).amount).toBe('0.85');
  });

  it('Copom não leva ativo', () => {
    const ok = eventFormSchema.parse({ ...base, kind: 'copom', ticker: '' });
    expect(toEventCreate(ok).ticker).toBeNull();
  });

  it('parseAmount rejeita zero, negativo e texto', () => {
    expect(parseAmount('0')).toBeNull();
    expect(parseAmount('-1')).toBeNull();
    expect(parseAmount('abc')).toBeNull();
    expect(parseAmount('1.2345678')).toBeNull();
    expect(parseAmount('1,25')).toBe('1.25');
  });
});
