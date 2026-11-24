// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SizingResponse } from '@vollab/api-types';
import fixture from './__fixtures__/long-straddle-sizing.json';
import SimulationResult from './SimulationResult';

vi.mock('@/lib/charts/Plot', () => ({ default: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} /> }));

afterEach(cleanup);

const data = fixture as unknown as SizingResponse;

describe('SimulationResult', () => {
  it('mostra semáforo, edge e rótulos de estimativa no topo (PRD-UI-01/02)', () => {
    render(<SimulationResult sim={data.simulation} sizing={data.sizing} />);
    const edge = screen.getByTestId('sim-edge');
    expect(within(edge).getByText('Edge líquido (comprar vol)')).toBeInTheDocument();
    expect(within(edge).getByText(/Estrutura de/)).toHaveTextContent('comprar vol');
    expect(within(edge).getAllByText('não calibrado').length).toBeGreaterThan(0);
    expect(within(edge).getByText('limiar não calibrado')).toBeInTheDocument();
    expect(screen.getAllByText('estimativa').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('IV constante')).toBeInTheDocument();
    expect(screen.getByText('não calibrada')).toBeInTheDocument(); // banda de delta
  });

  it('dimensionamento diz qual regra prevaleceu (PRD-UI-09)', () => {
    render(<SimulationResult sim={data.simulation} sizing={data.sizing} />);
    const s = screen.getByTestId('sim-sizing');
    expect(within(s).getByTestId('sim-size-final')).toHaveTextContent('66');
    expect(within(s).getByTestId('sim-size-rule')).toHaveTextContent('Prevaleceu o teto de perda');
    expect(within(s).getByText('Queda com alta de vol')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Histograma do P&L/ })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Payoff por lote/ })).toBeInTheDocument();
  });

  it('zero com explicação quando a direção é oposta (RN-SIZ-05)', () => {
    const sim = { ...data.simulation, structure: 'short_straddle' as const, direction: 'sell' as const, direction_match: false };
    const sizing = { ...data.sizing, n_kelly: 0, n_final: 0, rule: 'zero' as const, reason: 'a direção da estrutura é oposta à do sinal (RN-SIZ-05)' };
    render(<SimulationResult sim={sim} sizing={sizing} />);
    expect(screen.getByTestId('sim-size-final')).toHaveTextContent('0');
    expect(screen.getByText(/Tamanho zero: a direção da estrutura é oposta/)).toBeInTheDocument();
    expect(screen.getByText(/direção oposta à do sinal: o Kelly é zero/)).toBeInTheDocument();
  });

  it('preço e ativo manuais são rotulados (RF-SIM-03)', () => {
    render(<SimulationResult sim={data.simulation} sizing={data.sizing} />);
    const before = screen.queryAllByText('manual').length; // o spread normal não calibrado já é "manual"
    cleanup();
    const legs = data.simulation.legs.map((l, i) => (i === 0 ? { ...l, price_origin: 'manual' as const } : l));
    render(<SimulationResult sim={{ ...data.simulation, legs, spot_origin: 'manual' }} sizing={data.sizing} />);
    expect(screen.getAllByText('manual').length).toBe(before + 2);
  });

  it('distribuição indisponível mostra o motivo, nunca um número', () => {
    const sim = {
      ...data.simulation,
      distribution: { ...data.simulation.distribution, status: 'insufficient_data' as const, reason: '90 de 120 retornos diários na amostra', mean_brl: null },
    };
    render(<SimulationResult sim={sim} sizing={data.sizing} />);
    expect(within(screen.getByTestId('sim-distribution')).getByText(/Dados insuficientes: 90 de 120/)).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Histograma/ })).not.toBeInTheDocument();
  });
});
