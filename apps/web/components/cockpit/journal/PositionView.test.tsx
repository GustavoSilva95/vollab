// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PositionOut } from '@vollab/api-types';
import { Attribution, Entries, Marks, RiskFacts } from './PositionView';

vi.mock('@/lib/charts/Plot', () => ({ default: () => <div data-testid="plot" /> }));
afterEach(cleanup);

const position: PositionOut = {
  id: 7,
  created_at: '2026-11-17T18:00:00Z',
  ticker: 'PETR4',
  structure: 'short_straddle',
  direction: 'sell',
  expiry: '2026-12-18',
  lots: 1,
  edge_state: 'edge',
  model: 'combination',
  config_version_id: 3,
  overridden: false,
  status: 'open',
  rolled_from_position_id: null,
  pnl_total_brl: '12.30',
  last_mark_date: '2026-11-19',
  cs04_ratio: 0.21,
  error_days: 1,
  pending_expiry: [],
  ledger_error: null,
  as_of: '2026-11-17',
  engine_version: 'abc123',
  override_reason: null,
  note: null,
  entries: [
    {
      id: 1, kind: 'entry', instrument: 'PETRL44', series_id: 1, quantity: -100, price_brl: '2.40', fees_brl: '0.30',
      brokerage_brl: '0.00', executed_at: '2026-11-17T18:00:00Z', linked_entry_id: null, strike_after_brl: null,
      void_reason: null, note: null, voided_by: null,
    },
    {
      id: 3, kind: 'hedge', instrument: 'PETR4', series_id: null, quantity: 30, price_brl: '43.50', fees_brl: '0.39',
      brokerage_brl: '0.00', executed_at: '2026-11-18T17:00:00Z', linked_entry_id: null, strike_after_brl: null,
      void_reason: null, note: null, voided_by: 4,
    },
    {
      id: 4, kind: 'void', instrument: 'PETR4', series_id: null, quantity: 30, price_brl: '43.50', fees_brl: '0.00',
      brokerage_brl: '0.00', executed_at: '2026-11-19T15:00:00Z', linked_entry_id: 3, strike_after_brl: null,
      void_reason: 'hedge lançado em dobro', note: null, voided_by: null,
    },
  ],
  manual_inputs: [],
  decision_snapshot: {},
  holdings: [{ instrument: 'PETRL44', series_id: 1, quantity: -100 }],
  marks: [
    {
      trade_date: '2026-11-19', spot_brl: '42.67', stock_qty: 0, options_value_brl: '-158.00', stock_value_brl: '0.00',
      delta_shares: 12.5, gamma: -9.1, vega_per_point_brl: -4.8, theta_per_bd_brl: 3.2, stale: true,
      legs: [
        { code: 'PETRL44', quantity: -100, price_brl: '1.58', iv: 0.3264, origin: 'stale', delta: -0.4, gamma: 0.09,
          vega_per_point: 0.048, theta_per_bd: -0.032 },
      ],
    },
  ],
  attribution: [
    {
      trade_date: '2026-11-19', delta_brl: '10.00', gamma_brl: '-2.00', theta_brl: '3.20', vega_brl: '-1.00',
      residual_brl: '0.00', market_brl: '10.20', execution_brl: '0.00', total_brl: '10.20', stale: true, error_flag: true,
    },
  ],
  totals: {
    delta_brl: '10.00', gamma_brl: '-2.00', theta_brl: '3.20', vega_brl: '-1.00', residual_brl: '0.00',
    market_brl: '10.20', execution_brl: '-0.60', total_brl: '9.60',
  },
  cs04: { ratio: 0.21, target: 0.15, ok: false, error_days: 1 },
  delta_band: {
    as_of: '2026-11-19', delta_shares: 12.5, half_width_shares: 10, calibrated: false, state: 'outside',
  },
}; // prettier-ignore

describe('Operação (PRD 1.10 §8.1)', () => {
  it('a atribuição mostra o resíduo sempre, mesmo zero, e separa execução e custos', () => {
    render(<Attribution position={position} />);
    const table = screen.getByTestId('op-attribution');
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual(expect.arrayContaining(['Resíduo', 'Execução e custos', 'Delta', 'Vega']));
    expect(within(table).getAllByText('R$ 0,00').length).toBeGreaterThan(0);
    expect(within(table).getByText('resíduo alto')).toBeInTheDocument();
    expect(within(table).getByText('desatualizado')).toBeInTheDocument();
    expect(within(table).getByText('Acumulado')).toBeInTheDocument();
  });

  it('banda de delta fora, CS-04 acima da meta e rótulo não calibrado', () => {
    render(<RiskFacts position={position} />);
    expect(screen.getByTestId('op-delta-band')).toHaveAttribute('data-state', 'outside');
    expect(screen.getByText('Fora da banda')).toBeInTheDocument();
    expect(screen.getByText('não calibrado')).toBeInTheDocument();
    expect(screen.getByTestId('op-cs04')).toHaveTextContent('21,0%');
  });

  it('marcação rotula a origem da perna (desatualizado)', () => {
    render(<Marks position={position} />);
    expect(screen.getByText('desatualizado')).toBeInTheDocument();
  });

  it('lançamentos mostram o estorno ligado e o motivo', () => {
    render(<Entries position={position} />);
    expect(screen.getByText('estornado por #4')).toBeInTheDocument();
    expect(screen.getByText(/anula #3: hedge lançado em dobro/)).toBeInTheDocument();
  });
});
