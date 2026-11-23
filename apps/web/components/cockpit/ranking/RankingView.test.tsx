// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { EstimatedValue, RankingResponse, RankingRow } from '@vollab/api-types';
import { RankingTable } from './RankingView';

afterEach(cleanup);

const ev = (over: Partial<EstimatedValue> = {}): EstimatedValue => ({
  value: 0.3,
  ci_low: null,
  ci_high: null,
  ci_level: 0.9,
  status: 'ok',
  origin: 'observed',
  as_of: '2026-11-19',
  stale: false,
  reason: null,
  calibrated: null,
  ...over,
});

const missing = (reason: string): EstimatedValue => ev({ value: null, status: 'unavailable', reason });

function row(over: Partial<RankingRow>): RankingRow {
  return {
    position: 1,
    ticker: 'PETR4',
    as_of: '2026-11-19',
    state: 'edge',
    direction: 'buy',
    reason: null,
    approximate: false,
    horizon_bd: 21,
    model: 'combination',
    iv: ev({ value: 0.3265 }),
    iv_with_events: ev({ value: 0.3265 }),
    events_removed: [],
    forecast: ev({ value: 0.4839, ci_low: 0.3548, ci_high: 0.668, origin: 'estimated' }),
    normal_spread: ev({ value: 0.15, origin: 'manual', calibrated: false, reason: 'não calibrado: 0 de 8 janelas' }),
    normal_spread_pairs: 0,
    premium: ev({ value: -0.23, ci_low: -0.4417, ci_high: -0.0816, origin: 'estimated' }),
    relative_edge: ev({ value: -0.4753, ci_low: -0.9128, ci_high: -0.1686, origin: 'estimated' }),
    net_relative_edge: 0.4596,
    net_premium: 0.2224,
    expected_pnl_brl: '2.13',
    threshold: ev({ value: 0.01, origin: 'manual', calibrated: false }),
    required_sell: 0.0153,
    required_buy: 0.0154,
    costs: {
      option_spread_central: 0.0103,
      option_spread_conservative: 0.0136,
      option_spread_quoted: 0.1293,
      underlying_spread: 0.00023,
      underlying_spread_estimated: true,
      spread_days: 3,
      spread_series: 12,
      reference_contracts: 100,
      straddle_premium_brl: '3.13',
      straddle_vega_brl: '0.0958',
      spread_brl: '0.04',
      fees_brl: '0.01',
      brokerage_brl: '0.00',
      options_vol_pts: 0.0052,
      hedge_sell_vol_pts: 0.0052,
      hedge_buy_vol_pts: 0.0053,
      hedge_half_spread: 0.00042,
      hedge_interval_bd: 1,
      total_sell_vol_pts: 0.0053,
      total_buy_vol_pts: 0.0054,
    },
    iv_rank: missing('sem IV de prazo constante no pregão'),
    iv_percentile: missing('sem IV de prazo constante no pregão'),
    iv_rank_days: 0,
    skew: missing('sem strikes líquidos dos dois lados de K/F = 0.95'),
    skew_expiry: null,
    term_slope: { value: missing('sem dois vencimentos com IV ATM') },
    events: [],
    liquidity: { liquid_series: 181, option_trades: 24090, option_volume_brl: '110991872.00' },
    ...over,
  };
}

const data: RankingResponse = {
  expected_as_of: '2026-11-19',
  horizon_bd: 21,
  selected_model: 'combination',
  ci_level: 0.9,
  config_version_id: 3,
  engine_version: 'dev',
  rows: [
    row({}),
    row({
      position: 2,
      ticker: 'BBAS3',
      state: 'unavailable',
      direction: null,
      reason: 'sem IV de prazo constante calculada: rode a coleta',
      premium: missing('sem dado'),
      relative_edge: missing('sem dado'),
      net_relative_edge: null,
      net_premium: null,
      required_sell: null,
      required_buy: null,
      costs: null,
      liquidity: null,
    }),
  ],
};

describe('RankingTable (PRD 1.8 §8.1, PRD-UI-01/02/08)', () => {
  it('mostra o estado com texto e direção, e o número de edge', () => {
    render(<RankingTable data={data} />);
    const petr = screen.getByTestId('ranking-row-PETR4');
    expect(within(petr).getByText('Edge líquido (comprar vol)')).toBeInTheDocument();
    expect(within(petr).getByText('46,0%')).toBeInTheDocument(); // edge relativo líquido
    expect(within(petr).getByText('-23,0 pts')).toBeInTheDocument(); // prêmio
  });

  it('rotula spread normal e limiar não calibrados e o custo como estimativa', () => {
    render(<RankingTable data={data} />);
    const petr = screen.getByTestId('ranking-row-PETR4');
    expect(within(petr).getByText('não calibrado')).toBeInTheDocument();
    expect(within(petr).getByText('estimativa')).toBeInTheDocument();
    expect(screen.getByText(/Limiar 1,0 pts/)).toBeInTheDocument();
    expect(screen.getAllByText('não calibrado')).toHaveLength(3); // spread normal das 2 linhas + limiar
  });

  it('indisponível nunca mostra número; o motivo aparece', () => {
    render(<RankingTable data={data} />);
    const bbas = screen.getByTestId('ranking-row-BBAS3');
    expect(within(bbas).getByText('Indisponível')).toHaveAttribute('title', expect.stringContaining('rode a coleta'));
    expect(within(bbas).queryByText(/pts/)).not.toBeInTheDocument();
  });

  it('a linha expandida discrimina os custos e o spread de fechamento como conferência', () => {
    render(<RankingTable data={data} />);
    fireEvent.click(screen.getByRole('button', { name: 'Detalhes de PETR4' }));
    expect(screen.getByText(/fechamento COTAHIST \(conferência\)/)).toBeInTheDocument();
    expect(screen.getByText(/Hedge \(Leland/)).toBeInTheDocument();
    expect(screen.getByText(/R\$\s?2,13/)).toBeInTheDocument();
  });
});
