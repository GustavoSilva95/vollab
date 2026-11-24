// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { LimitsResponse } from '@vollab/api-types';
import { Limits } from './PortfolioView';

afterEach(cleanup);

const limits: LimitsResponse = {
  capital_brl: '100000.00',
  scenarios: [],
  breached: true,
  warnings: [],
  limits: [
    { name: 'stress_loss', scope: null, value: 0.25, limit: 0.2, usage: 1.25, state: 'breached', reason: null, calibrated: false },
    { name: 'vega_total', scope: null, value: 0.002, limit: 0.01, usage: 0.2, state: 'ok', reason: null, calibrated: false },
    { name: 'underlying_concentration', scope: 'PETR4', value: 0.5, limit: 0.5, usage: 1, state: 'ok', reason: null, calibrated: false },
  ],
}; // prettier-ignore

describe('Limites da carteira (RF-RSK-04)', () => {
  it('estado com texto, valores em % só na tela e rótulo não calibrado', () => {
    render(<Limits limits={limits} />);
    const table = screen.getByTestId('pf-limits');
    expect(within(table).getByText('Ultrapassado')).toBeInTheDocument();
    expect(within(table).getAllByText('não calibrado')).toHaveLength(3);
    expect(within(table).getByText('125,0%')).toBeInTheDocument();
    expect(within(table).getByText(/PETR4/)).toBeInTheDocument();
  });

  it('sem capital, avisa que os limites ficam indisponíveis', () => {
    render(<Limits limits={{ ...limits, capital_brl: null, breached: false }} />);
    expect(screen.getByText(/limites ficam indisponíveis/)).toBeInTheDocument();
  });
});
