// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { EstimatedValue, EvaluationResponse, ForecastsResponse } from '@vollab/api-types';
import { EvaluationTable, ForecastTable } from './ModelsView';

afterEach(cleanup);

const ev = (over: Partial<EstimatedValue> = {}): EstimatedValue => ({
  value: 0.42,
  ci_low: 0.31,
  ci_high: 0.53,
  ci_level: 0.9,
  status: 'ok',
  origin: 'estimated',
  as_of: '2026-11-19',
  stale: false,
  reason: null,
  calibrated: null,
  ...over,
});

const forecasts: ForecastsResponse = {
  ticker: 'PETR4',
  as_of: '2026-11-19',
  horizon_bd: 21,
  evaluated_horizons_bd: [21],
  selected_model: 'ewma',
  ci_level: 0.9,
  items: [
    {
      model: 'ewma',
      kind: 'model',
      forecast: ev({ origin: 'approximate', reason: 'intervalo só com o erro de amostragem (< 8 janelas avaliadas)' }),
      selected: true,
      eligible: false,
      eligibility_reason: 'dados insuficientes: 7 de 8 janelas a 21 pregões',
      state: { ewma_lambda: 0.94, n_returns: 220 },
    },
    {
      model: 'combination',
      kind: 'model',
      forecast: ev({ value: 0.4839 }),
      selected: false,
      eligible: true,
      eligibility_reason: null,
      state: { components: ['close_to_close', 'yang_zhang', 'rogers_satchell'], window_bd: 20, n_returns: 220 },
    },
    {
      model: 'garch',
      kind: 'model',
      forecast: ev({ value: null, status: 'insufficient_data', reason: '220 retornos; mínimo de 240' }),
      selected: false,
      eligible: false,
      eligibility_reason: 'dados insuficientes: 0 de 8 janelas a 21 pregões',
      state: { n_returns: 220 },
    },
    {
      model: 'rv_c2c_20',
      kind: 'baseline',
      forecast: ev({ value: 0.33, origin: 'observed', ci_low: null, ci_high: null }),
      selected: false,
      eligible: false,
      eligibility_reason: 'baseline: não alimenta o edge',
    },
  ],
};

describe('ForecastTable (RF-PRV-04, PRD-UI-02/08)', () => {
  it('mostra o modelo em uso, avisa que ele não é elegível e rotula o intervalo aproximado', () => {
    render(<ForecastTable data={forecasts} />);
    expect(screen.getByText(/Modelo em uso no edge: EWMA/)).toBeInTheDocument();
    expect(screen.getByText(/o edge fica indisponível/)).toBeInTheDocument();
    const ewmaRow = screen.getByRole('rowheader', { name: /EWMA/ }).closest('tr')!;
    expect(within(ewmaRow).getByText('aproximado')).toBeInTheDocument();
    expect(within(ewmaRow).getByText('[31,00% – 53,00%]')).toBeInTheDocument();
  });

  it('GARCH sem amostra mostra "dados insuficientes" e nunca um número', () => {
    render(<ForecastTable data={forecasts} />);
    const row = screen.getByRole('rowheader', { name: /GARCH/ }).closest('tr')!;
    expect(within(row).getByText('dados insuficientes')).toHaveAttribute('title', '220 retornos; mínimo de 240');
    expect(within(row).getByText('não elegível')).toBeInTheDocument();
    expect(within(row).queryByText(/%/)).not.toBeInTheDocument();
  });

  it('só oferece a troca para modelos elegíveis', () => {
    const onSelect = vi.fn();
    render(<ForecastTable data={forecasts} onSelect={onSelect} />);
    const buttons = screen.getAllByRole('button', { name: 'Usar no edge' });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]!);
    expect(onSelect).toHaveBeenCalledWith('combination');
    const baseline = screen.getByRole('rowheader', { name: /Baseline: RV/ }).closest('tr')!;
    expect(within(baseline).getByText('baseline')).toBeInTheDocument();
  });
});

const evaluation: EvaluationResponse = {
  ticker: 'PETR4',
  horizon_bd: 21,
  evaluated_horizons_bd: [21],
  min_windows: 8,
  ci_level: 0.9,
  selected_model: 'ewma',
  computed_at: '2026-11-20T10:00:00Z',
  config_version_id: 3,
  engine_version: 'abc1234',
  rows: [
    {
      model: 'ewma',
      kind: 'model',
      status: 'insufficient_data',
      n_windows: 7,
      discarded_no_forecast: 3,
      discarded_incomplete_realized: 0,
      first_origin: '2026-04-01',
      last_origin: '2026-10-21',
      bias: null,
      mae: null,
      rmse: ev({ value: null, status: 'insufficient_data', reason: '7 de 8 janelas necessárias' }),
      ratios: [
        {
          baseline: 'rv_c2c_20',
          n_windows: 7,
          ratio: ev({ value: null, status: 'insufficient_data', reason: '7 de 8 janelas pareadas' }),
        },
      ],
    },
    {
      model: 'combination',
      kind: 'model',
      status: 'ok',
      n_windows: 9,
      discarded_no_forecast: 1,
      discarded_incomplete_realized: 0,
      first_origin: '2026-02-02',
      last_origin: '2026-10-21',
      bias: 0.021,
      mae: 0.05,
      rmse: ev({ value: 0.0832, ci_low: 0.05, ci_high: 0.11 }),
      ratios: [
        { baseline: 'rv_c2c_20', n_windows: 9, ratio: ev({ value: 1.2258, ci_low: 0.97, ci_high: 1.52 }) },
        {
          baseline: 'implied',
          n_windows: 0,
          ratio: ev({ value: null, status: 'insufficient_data', reason: '0 de 8 janelas pareadas' }),
        },
      ],
    },
  ],
};

describe('EvaluationTable (RF-PRV-03, RN-PRV-01/02, CS-03)', () => {
  it('mostra erro em pontos de vol, intervalo e razão contra os baselines', () => {
    render(<EvaluationTable data={evaluation} />);
    const row = screen.getByRole('rowheader', { name: /Combinação/ }).closest('tr')!;
    expect(within(row).getByText('8,3 pts')).toBeInTheDocument();
    expect(within(row).getByText('2,1 pts')).toBeInTheDocument();
    expect(within(row).getByText('1,23')).toBeInTheDocument();
    expect(within(row).getByText('[0,97 – 1,52]')).toBeInTheDocument();
    expect(within(row).getByText('9')).toBeInTheDocument();
  });

  it('abaixo da amostra mínima: sem número, com o motivo', () => {
    render(<EvaluationTable data={evaluation} />);
    const row = screen.getByRole('rowheader', { name: /EWMA/ }).closest('tr')!;
    expect(within(row).getAllByText('dados insuficientes')[0]).toHaveAttribute('title', '7 de 8 janelas necessárias');
    expect(within(row).queryByText(/pts/)).not.toBeInTheDocument();
    expect(screen.getByText(/Abaixo de 8 janelas: dados insuficientes/)).toBeInTheDocument();
  });
});
