/**
 * Textos dos alertas (PRD 1.11 §5.10 e §8.1): números do disparo formatados pelo `lib/format`,
 * nunca com % ou float de dinheiro vindos da API.
 */
import { describe, expect, it } from 'vitest';
import { RULE_LABEL, describeDetails as describeRaw, relativeText, ruleText, uncalibrated } from './labels';

/** Intl usa espaço não separável em "R$ 1,00" e "5 du": normaliza para comparar. */
const describeDetails = (...args: Parameters<typeof describeRaw>) => describeRaw(...args).replace(/\s/g, ' ');

describe('describeDetails', () => {
  it('hedge: delta, banda e o ajuste até a borda', () => {
    expect(describeDetails('hedge_band', { delta_shares: 12.5, half_width_shares: 10, adjust_shares: -3 })).toBe(
      'Δ 12,5 ações (banda ± 10) · ajuste até a borda: vender 3 ações',
    );
    expect(describeDetails('hedge_time', { bd_since_last_hedge: 6, interval_bd: 5 })).toBe('6 du sem hedge (intervalo 5 du)');
  });

  it('saída: edge relativo líquido com intervalo e prazo', () => {
    expect(describeDetails('exit_edge', { net_relative_edge: -0.4925, ci_low: -0.93, ci_high: -0.1857 })).toBe(
      'Edge relativo líquido -49,3% [-93,0%; -18,6%]',
    );
    expect(describeDetails('exit_edge', { net_relative_edge: null })).toMatch(/hedge consome/);
    expect(describeDetails('exit_dte', { days_to_expiry_bd: 5, max_bd: 5 })).toBe('5 du até o vencimento (limite 5 du)');
    expect(describeDetails('exit_stop', { pnl_brl: '-310.00', stop_brl: '-300.00' })).toBe('P&L -R$ 310,00 ≤ stop -R$ 300,00');
  });

  it('rolagem, limite, provento e ajuste de strike', () => {
    expect(
      describeDetails('roll_suggested', {
        expiry: '2026-12-18',
        horizon_bd: 20,
        legs: [{ code: 'PETRL44' }, { code: 'PETRX44' }],
        net_relative_edge: 0.25,
        close_cost_brl: '2.05',
      }),
    ).toBe('Para 18/12/2026 (20 du) · PETRL44 + PETRX44 · edge relativo líquido 25,0% com o custo de fechar R$ 2,05');
    expect(describeDetails('limit_stress', { limit: 'stress_loss', scope: null, value: 1.5, limit_value: 0.2 })).toBe(
      'Pior perda em stress ÷ capital: 150,0% > 20,0%',
    );
    expect(
      describeDetails('dividend_upcoming', {
        ex_date: '2026-11-27',
        days_to_ex_bd: 5,
        items: [{ amount_brl: '0.500000', source: 'manual' }],
      }),
    ).toBe('Data ex em 27/11/2026, em 5 du · R$ 0,5000 (manual)');
    expect(
      describeDetails('strike_adjustment_pending', {
        code: 'PETRL44',
        old_strike_brl: '44.00',
        new_strike_brl: '43.50',
        effective_date: '2026-11-19',
      }),
    ).toBe('PETRL44: strike R$ 44,00 → R$ 43,50 desde 19/11/2026. Lance o ajuste de strike.');
  });

  it('razões muito grandes não derrubam a tela', () => {
    expect(relativeText(150)).toBe('> 2.000%');
    expect(relativeText(null)).toBe('—');
  });
});

describe('ruleText e rótulos', () => {
  it('estado desligado, indisponível e rolagem sem edge', () => {
    expect(ruleText({ rule: 'exit_stop', state: 'disabled', reason: null, details: {} })).toBe('Desligada nas configurações.');
    expect(ruleText({ rule: 'exit_edge', state: 'unavailable', reason: 'sem previsão', details: {} })).toBe('sem previsão');
    expect(
      ruleText({ rule: 'roll_suggested', state: 'ok', reason: 'rolagem avaliada: sem edge líquido na direção', details: { suggested: false } }),
    ).toBe('rolagem avaliada: sem edge líquido na direção');
  });

  it('todas as regras têm rótulo; ajuste de strike e edge não são parâmetros sem calibração', () => {
    expect(Object.keys(RULE_LABEL)).toHaveLength(13);
    expect(uncalibrated('strike_adjustment_pending')).toBe(false);
    expect(uncalibrated('hedge_band')).toBe(true);
  });
});
