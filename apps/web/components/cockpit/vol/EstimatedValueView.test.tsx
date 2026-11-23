// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { EstimatedValue } from '@vollab/api-types';
import EstimatedValueView from './EstimatedValueView';

afterEach(cleanup);

const base: EstimatedValue = {
  value: 0.3264,
  ci_low: null,
  ci_high: null,
  ci_level: 0.9,
  status: 'ok',
  origin: 'estimated',
  as_of: '2026-11-19',
  stale: false,
  reason: null,
  calibrated: null,
};

describe('EstimatedValueView (PRD §5.2, PRD-UI-02/08)', () => {
  it('mostra o valor formatado e o rótulo de estimado', () => {
    render(<EstimatedValueView value={base} />);
    expect(screen.getByText('32,64%')).toBeInTheDocument();
    expect(screen.getByText('estimado')).toHaveAttribute('title');
  });

  it('dados insuficientes nunca mostram número, e o motivo fica acessível', () => {
    render(
      <EstimatedValueView
        value={{ ...base, value: 0.31, status: 'insufficient_data', reason: 'pregões ausentes ou inválidos na janela' }}
      />,
    );
    expect(screen.queryByText(/31/)).not.toBeInTheDocument();
    expect(screen.getByText('dados insuficientes')).toHaveAttribute('title', 'pregões ausentes ou inválidos na janela');
  });

  it('indisponível com motivo', () => {
    render(<EstimatedValueView value={{ ...base, value: null, status: 'unavailable', reason: 'sem dois vencimentos' }} />);
    expect(screen.getByText('indisponível')).toBeInTheDocument();
  });

  it('marca dado desatualizado e mostra o intervalo quando pedido', () => {
    render(<EstimatedValueView value={{ ...base, stale: true, ci_low: 0.3, ci_high: 0.35 }} showInterval />);
    expect(screen.getByText('desatualizado')).toBeInTheDocument();
    expect(screen.getByText(/30,00%/)).toBeInTheDocument();
  });

  it('valor observado não leva rótulo de origem', () => {
    render(<EstimatedValueView value={{ ...base, origin: 'observed' }} />);
    expect(screen.queryByText('estimado')).not.toBeInTheDocument();
  });
});
