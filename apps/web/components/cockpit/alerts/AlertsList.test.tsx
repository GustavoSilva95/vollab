// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { client, type AlertOut, type PositionOut } from '@vollab/api-types';
import { Management } from '../journal/PositionView';
import AlertsList from './AlertsList';

vi.mock('@/lib/charts/Plot', () => ({ default: () => <div data-testid="plot" /> }));
beforeEach(() => {
  client.setConfig({ baseUrl: 'http://127.0.0.1/api/engine' });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ALERT: AlertOut = {
  id: 11,
  kind: 'hedge',
  rule: 'hedge_band',
  position_id: 7,
  ticker: 'PETR4',
  structure: 'short_straddle',
  scope_key: '',
  state: 'active',
  triggered_at: '2026-11-20T10:00:00Z',
  triggered_as_of: '2026-11-19',
  last_as_of: '2026-11-19',
  details: { delta_shares: 12.5, half_width_shares: 10, adjust_shares: -3, calibrated: false },
  config_version_id: 4,
  evaluated_config_version_id: 4,
  engine_version: 'abc',
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
};

function renderWith(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function mockPatch() {
  const bodies: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      const text = await input.text();
      const body = JSON.parse(text || '{}') as { state: AlertOut['state']; note?: string };
      bodies.push({ method: input.method, url: input.url, body });
      return Response.json({ ...ALERT, state: body.state, resolution_note: body.note ?? null });
    }),
  );
  return bodies;
}

describe('Alertas (PRD 1.11 §8.1; RN-GES-07, PRD-UI-10)', () => {
  it('tipo, regra e estado com texto, números do disparo e rótulo não calibrado', () => {
    renderWith(<AlertsList alerts={[ALERT]} />);
    const item = screen.getByTestId('alert-hedge_band');
    expect(item).toHaveAttribute('data-state', 'active');
    expect(within(item).getByText('Hedge')).toBeInTheDocument();
    expect(within(item).getByText('Delta fora da banda')).toBeInTheDocument();
    expect(within(item).getByTestId('alert-state')).toHaveTextContent('Ativo');
    expect(within(item).getByText('não calibrado')).toBeInTheDocument();
    expect(item.textContent).toMatch(/vender\s3\sações/);
    expect(within(item).getByRole('link')).toHaveAttribute('href', '/app/operacoes/7');
    expect(item.textContent).toMatch(/configuração v4/);
  });

  it('marcar como visto e resolver com nota mandam o PATCH', async () => {
    const calls = mockPatch();
    renderWith(<AlertsList alerts={[ALERT]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Marcar como visto' }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: 'PATCH', body: { state: 'seen' } });
    fireEvent.click(screen.getByRole('button', { name: 'Resolver' }));
    fireEvent.change(screen.getByLabelText('Nota da resolução'), { target: { value: ' vou manter ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toMatchObject({ body: { state: 'resolved', note: 'vou manter' } });
  });

  it('resolvido não tem ações e mostra quem resolveu; limite é da carteira', () => {
    const done: AlertOut = {
      ...ALERT,
      id: 12,
      kind: 'limit',
      rule: 'limit_stress',
      position_id: null,
      ticker: null,
      structure: null,
      state: 'resolved',
      details: { limit: 'stress_loss', scope: null, value: 0.3, limit_value: 0.2 },
      resolved_at: '2026-11-21T10:00:00Z',
      resolved_by: 'auto',
      resolution_note: 'a condição deixou de valer',
    };
    renderWith(<AlertsList alerts={[done]} />);
    const item = screen.getByTestId('alert-limit_stress');
    expect(within(item).queryByRole('button')).toBeNull();
    expect(item.textContent).toMatch(/resolvido automaticamente: a condição deixou de valer/);
    expect(within(item).getByText('Carteira')).toBeInTheDocument();
  });

  it('rolagem sugerida leva ao simulador com a origem', () => {
    const roll: AlertOut = {
      ...ALERT,
      id: 13,
      kind: 'roll',
      rule: 'roll_suggested',
      details: { expiry: '2026-12-18', horizon_bd: 20, legs: [], net_relative_edge: 0.2, close_cost_brl: '2.05' },
    };
    renderWith(<AlertsList alerts={[roll]} />);
    expect(screen.getByTestId('alert-roll-link')).toHaveAttribute(
      'href',
      '/app/simulador?roll_from=7&expiry=2026-12-18&ticker=PETR4&structure=short_straddle',
    );
  });

  it('vencimento fora do formato ISO não gera link (nenhum parâmetro injetado)', () => {
    const forged: AlertOut = {
      ...ALERT,
      id: 14,
      kind: 'roll',
      rule: 'roll_suggested',
      details: { expiry: '2026-12-18&roll_from=99', horizon_bd: 20, legs: [], net_relative_edge: 0.2, close_cost_brl: '2.05' },
    };
    renderWith(<AlertsList alerts={[forged]} />);
    expect(screen.queryByTestId('alert-roll-link')).toBeNull();
    expect(screen.getByText('Detalhe do alerta em formato inesperado.')).toBeInTheDocument();
  });
});

describe('Gestão na operação (PRD 1.11 §8.1)', () => {
  const base = { id: 7, ticker: 'PETR4', structure: 'short_straddle', status: 'open' } as PositionOut;

  it('os quatro estados das regras, o edge da posição com intervalo e os alertas', () => {
    const position = {
      ...base,
      management: {
        as_of: '2026-11-19',
        evaluated_at: '2026-11-20T10:00:00Z',
        config_version_id: 4,
        rules: [
          { rule: 'hedge_band', kind: 'hedge', state: 'triggered', scope_key: '', reason: null, details: ALERT.details },
          { rule: 'hedge_time', kind: 'hedge', state: 'disabled', scope_key: '', reason: null, details: {} },
          {
            rule: 'exit_edge',
            kind: 'exit',
            state: 'ok',
            scope_key: '',
            reason: null,
            details: { net_relative_edge: 0.2, ci_low: 0.05, ci_high: 0.4 },
          },
          { rule: 'exit_profit', kind: 'exit', state: 'unavailable', scope_key: '', reason: 'P&L esperado ≤ 0', details: {} },
        ],
        edge: {
          as_of: '2026-11-19',
          horizon_bd: 20,
          iv: 0.33,
          iv_with_events: 0.33,
          sigma: 0.25,
          sigma_low: 0.2,
          sigma_high: 0.3,
          normal_spread: 0.15,
          normal_spread_calibrated: false,
          premium: 0.04,
          premium_low: 0.0,
          premium_high: 0.1,
          cost_hold_vol_pts: 0.005,
          cost_close_vol_pts: 0.002,
          cost_close_brl: '2.05',
          net_relative_edge: 0.2,
          net_relative_low: 0.05,
          net_relative_high: 0.4,
          origin: 'approximate',
          model: 'combination',
          reason: null,
        },
        roll: null,
        alerts: [ALERT],
      },
    } as PositionOut;
    renderWith(<Management position={position} />);
    const states = ['hedge_band', 'hedge_time', 'exit_edge', 'exit_profit'].map(
      (r) => within(screen.getByTestId(`rule-${r}`)).getAllByText(/Disparada|Desligada|OK|Indisponível/)[0]?.textContent,
    );
    expect(states).toEqual(['Disparada', 'Desligada', 'OK', 'Indisponível']);
    expect(screen.getByText(/P&L esperado ≤ 0/)).toBeInTheDocument();
    const edge = screen.getByTestId('op-position-edge');
    expect(edge.textContent).toMatch(/20,0%/);
    expect(edge.textContent).toMatch(/\[5,0%; 40,0%\]/);
    expect(within(edge).getByText('aproximado')).toBeInTheDocument();
    expect(screen.getByTestId('alert-hedge_band')).toBeInTheDocument();
  });

  it('sem avaliação ainda', () => {
    renderWith(<Management position={{ ...base, management: null }} />);
    expect(screen.getByTestId('op-management').textContent).toMatch(/Ainda sem avaliação/);
  });
});
