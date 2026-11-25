/**
 * T-REF-06 (parte web): unidades e escalas (PRD §10.2, §5.1).
 * Vol decimal × %, dias úteis × corridos, taxa decimal; nenhuma função aceita %.
 */
import { describe, expect, it } from 'vitest';
import {
  EMPTY,
  formatBusinessDays,
  formatCalendarDays,
  formatDate,
  formatDateTime,
  formatDuration,
  formatFraction,
  formatMoney,
  formatNumber,
  formatRate,
  formatRatio,
  formatReturn,
  formatShare,
  formatVol,
  formatVolPoints,
} from './index';

const NBSP = ' ';

describe('formatVol — decimal anualizado (base 252) → %', () => {
  it.each([
    [0.2534, '25,34%'],
    [0.1, '10,00%'],
    [0, '0,00%'],
    [1.5, '150,00%'],
    [-0.0312, '-3,12%'],
  ])('%s → %s', (vol, expected) => {
    expect(formatVol(vol)).toBe(expected);
  });

  it('aceita precisão explícita', () => {
    expect(formatVol(0.25345, 3)).toBe('25,345%');
  });

  it('não exibe "-0,00%" para valores que arredondam a zero', () => {
    expect(formatVol(-0.000001)).toBe('0,00%');
    expect(formatVol(-0)).toBe('0,00%');
  });

  it('rejeita percentual passado por engano (25.34 em vez de 0.2534)', () => {
    expect(() => formatVol(25.34)).toThrow(RangeError);
    expect(() => formatVol(-25.34)).toThrow(/escala decimal/);
  });

  it('rejeita valores não finitos', () => {
    expect(() => formatVol(Number.NaN)).toThrow(RangeError);
    expect(() => formatVol(Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });

  it('valor ausente vira traço, nunca zero', () => {
    expect(formatVol(null)).toBe(EMPTY);
    expect(formatVol(undefined)).toBe(EMPTY);
  });
});

describe('formatVolPoints — prêmio de vol em decimal → pontos', () => {
  it('1 ponto = 0,01', () => {
    expect(formatVolPoints(0.031)).toBe(`3,1${NBSP}pts`);
    expect(formatVolPoints(0.01)).toBe(`1,0${NBSP}pts`);
    expect(formatVolPoints(-0.0025, 2)).toBe(`-0,25${NBSP}pts`);
  });

  it('rejeita prêmio em pontos ou em % (3.1 em vez de 0.031)', () => {
    expect(() => formatVolPoints(3.1)).toThrow(RangeError);
  });
});

describe('formatRate — taxa decimal anual exponencial', () => {
  it('0.1365 → 13,65% a.a.', () => {
    expect(formatRate(0.1365)).toBe(`13,65%${NBSP}a.a.`);
  });

  it('rejeita taxa em % (13.65, como vem do SGS antes da conversão)', () => {
    expect(() => formatRate(13.65)).toThrow(RangeError);
  });
});

describe('dias úteis × corridos', () => {
  it('sufixos distintos e explícitos', () => {
    expect(formatBusinessDays(21)).toBe(`21${NBSP}du`);
    expect(formatCalendarDays(30)).toBe(`30${NBSP}dc`);
    expect(formatBusinessDays(1260)).toBe(`1.260${NBSP}du`);
  });

  it('rejeita fração de dia (provável anos úteis passados como dias)', () => {
    expect(() => formatBusinessDays(21 / 252)).toThrow(/inteiros/);
    expect(() => formatCalendarDays(0.5)).toThrow(RangeError);
  });
});

describe('formatMoney — BRL com decimal exato', () => {
  it('string decimal da API, sem perda por float', () => {
    expect(formatMoney('1234.56')).toBe(`R$${NBSP}1.234,56`);
    expect(formatMoney('0.1')).toBe(`R$${NBSP}0,10`);
    // 2^53 + 1 não é representável em float; como string, sai exato.
    expect(formatMoney('9007199254740993.00')).toBe(`R$${NBSP}9.007.199.254.740.993,00`);
  });

  it('números e negativos', () => {
    expect(formatMoney(-250)).toBe(`-R$${NBSP}250,00`);
    expect(formatMoney('-0.004')).toBe(`R$${NBSP}0,00`);
  });

  it('rejeita strings que não são decimal', () => {
    expect(() => formatMoney('1,5')).toThrow(RangeError);
    expect(() => formatMoney('R$ 10')).toThrow(RangeError);
  });

  it('ausente vira traço', () => {
    expect(formatMoney(null)).toBe(EMPTY);
  });
});

describe('formatNumber', () => {
  it('separador de milhar pt-BR', () => {
    expect(formatNumber(35_000)).toBe('35.000');
    expect(formatNumber(1234.5, 1)).toBe('1.234,5');
  });
});

describe('datas', () => {
  it('data de pregão não muda de dia por fuso', () => {
    expect(formatDate('2026-11-22')).toBe('22/11/2026');
    expect(formatDate('2026-01-01')).toBe('01/01/2026');
  });

  it('rejeita formato errado', () => {
    expect(() => formatDate('22/11/2026')).toThrow(RangeError);
  });

  it('instante sempre no horário de Brasília', () => {
    // 17:59:13 UTC = 14:59:13 em São Paulo (UTC−3, sem horário de verão).
    expect(formatDateTime('2026-11-22T17:59:13Z')).toBe('22/11/2026 14:59:13');
    // Virada de dia: 01:30 UTC ainda é o dia anterior em São Paulo.
    expect(formatDateTime('2026-11-23T01:30:00+00:00')).toBe('22/11/2026 22:30:00');
  });

  it('rejeita instante inválido', () => {
    expect(() => formatDateTime('ontem')).toThrow(RangeError);
  });
});

describe('formatDuration', () => {
  it('segundos, minutos e horas', () => {
    expect(formatDuration(45)).toBe('45 s');
    expect(formatDuration(290)).toBe('5 min');
    expect(formatDuration(18_000)).toBe('5 h 00 min');
    expect(formatDuration(18_130)).toBe('5 h 02 min');
    expect(formatDuration(null)).toBe(EMPTY);
  });

  it('rejeita negativo e não finito', () => {
    expect(() => formatDuration(-1)).toThrow(RangeError);
    expect(() => formatDuration(Number.NaN)).toThrow(RangeError);
  });
});

describe('formatShare', () => {
  it('proporção em percentual inteiro', () => {
    expect(formatShare(40, 100)).toMatch(/^40\s?%$/);
    expect(formatShare(0, 0)).toBe(EMPTY);
    expect(() => formatShare(5, 4)).toThrow(RangeError);
  });
});

describe('formatFraction, formatReturn e formatRatio (Etapa 3)', () => {
  it('fração e retorno em decimal viram percentual', () => {
    expect(formatFraction(0.9896)).toBe('99,0%');
    expect(formatReturn(0.0435)).toBe('4,35%');
    expect(formatReturn(-0.1364)).toBe('-13,64%');
    expect(formatRatio(1.0512)).toBe('1,05');
  });

  it('rejeitam percentual passado por engano', () => {
    expect(() => formatFraction(98.9)).toThrow(RangeError);
    expect(() => formatReturn(4.35)).toThrow(RangeError);
  });

  it('ausente vira EMPTY', () => {
    expect(formatFraction(null)).toBe(EMPTY);
    expect(formatReturn(undefined)).toBe(EMPTY);
    expect(formatRatio(null)).toBe(EMPTY);
  });
});

describe('Etapa 5: edge relativo, taxas e entradas de formulário (PRD 1.8)', async () => {
  const f = await import('./index');

  it('formatRelative aceita valores fora de 0..1 e negativos, em decimal', () => {
    expect(f.formatRelative(0.25)).toBe(`25,0%`);
    expect(f.formatRelative(-0.475)).toBe(`-47,5%`);
    expect(f.formatRelative(1.5)).toBe(`150,0%`);
    expect(f.formatRelative(null)).toBe(EMPTY);
    expect(() => f.formatRelative(25)).toThrow(RangeError); // percentual por engano
  });

  it('formatSmallRate mostra taxas pequenas sem zeros à direita', () => {
    expect(f.formatSmallRate(0.00134)).toBe(`0,134%`);
    expect(f.formatSmallRate(0)).toBe(`0%`);
    expect(() => f.formatSmallRate(1.34)).toThrow(RangeError);
  });

  it('entradas em % e em pontos viram decimal, e voltam', () => {
    expect(f.parsePercentInput('0,134')).toBe(0.00134);
    expect(f.parsePercentInput('15')).toBe(0.15);
    expect(f.parsePercentInput('0.03')).toBe(0.0003);
    expect(f.parsePercentInput('abc')).toBeNull();
    expect(f.parsePercentInput('1,2,3')).toBeNull();
    expect(f.parseVolPointsInput('1')).toBe(0.01);
    expect(f.toPercentInput(0.00134)).toBe('0,134');
    expect(f.toVolPointsInput(0.01)).toBe('1');
    expect(f.parsePlainInput('0,95')).toBe(0.95);
    expect(f.toPlainInput(0.95)).toBe('0,95');
  });
});

describe('entradas do simulador (Etapa 6)', () => {
  it('converte dinheiro digitado em decimal exato, sem float', async () => {
    const { parseMoneyInput, toMoneyInput } = await import('./index');
    expect(parseMoneyInput('1,80')).toBe('1.80');
    expect(parseMoneyInput('R$ 42,67')).toBe('42.67');
    expect(parseMoneyInput('100000')).toBe('100000');
    expect(parseMoneyInput('0,1234567')).toBeNull();
    expect(parseMoneyInput('0')).toBeNull();
    expect(parseMoneyInput('-1')).toBeNull();
    expect(parseMoneyInput('1.234,56')).toBeNull();
    expect(toMoneyInput('1.80')).toBe('1,80');
  });

  it('usa o fuso da B3 para data e hora digitadas', async () => {
    const { nowMarketInput, marketInputToIso } = await import('./index');
    expect(nowMarketInput(new Date('2026-11-19T20:30:00Z'))).toBe('2026-11-19T17:30');
    expect(marketInputToIso('2026-11-19T17:30')).toBe('2026-11-19T17:30:00-03:00');
    expect(marketInputToIso('19/11/2026 17:30')).toBeNull();
  });
});

describe('Etapa 7: choque de vol e dinheiro zero', () => {
  it('formatVolShock aceita choques de crise acima de 100 pontos, com sinal', async () => {
    const { formatVolShock } = await import('./index');
    expect(formatVolShock(1.159)).toBe('+115,9 pts');
    expect(formatVolShock(-0.05)).toBe('-5,0 pts');
    expect(formatVolShock(0)).toBe('0,0 pts');
    expect(() => formatVolShock(25)).toThrow(RangeError); // percentual por engano
  });

  it('parseMoneyOrZeroInput aceita zero e decimais com vírgula', async () => {
    const { parseMoneyOrZeroInput } = await import('./index');
    expect(parseMoneyOrZeroInput('0')).toBe('0');
    expect(parseMoneyOrZeroInput('0,00')).toBe('0');
    expect(parseMoneyOrZeroInput('1,80')).toBe('1.80');
    expect(parseMoneyOrZeroInput('-1')).toBeNull();
  });
});

