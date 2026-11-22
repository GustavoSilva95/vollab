// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { client, type CollectionPendingResponse } from '@vollab/api-types';
import { isCollectionQuery } from '@/lib/collection/useStartCollection';
import CollectionPendingCard from './CollectionPendingCard';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const BASE: CollectionPendingResponse = {
  reference_date: '2026-11-19',
  intraday_start: '2026-08-20',
  bars_start: '2025-11-18',
  is_initial_load: true,
  pending_days: ['2026-11-18', '2026-11-19'],
  counts: [
    { group: 'cotahist_annual', count: 2 },
    { group: 'cotahist_daily', count: 63 },
    { group: 'selic', count: 1 },
    { group: 'dividends', count: 3 },
    { group: 'underlying_trades', count: 189 },
    { group: 'option_trades', count: 0 },
  ],
  known_requests: 258,
  days_awaiting_cotahist: 63,
  estimated_seconds: 258,
  requests_per_second: 1,
  data_source: 'fixtures',
  active_run: null,
  last_run: null,
};

function mockEngine(pending: CollectionPendingResponse) {
  const calls: Request[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request) => {
      calls.push(input);
      if (input.method === 'POST') {
        return Response.json({ detail: 'Já existe uma coleta em andamento.', status: 409, title: 'Conflict' }, {
          status: 409,
          headers: { 'content-type': 'application/problem+json' },
        });
      }
      return Response.json(pending);
    }),
  );
  return calls;
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CollectionPendingCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  push.mockReset();
  // O Request do Node não resolve URL relativa; no navegador a base é `/api/engine` (ADR-09).
  client.setConfig({ baseUrl: 'http://127.0.0.1/api/engine' });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('CollectionPendingCard', () => {
  it('mostra pregões pendentes, contagens, tempo e a fonte simulada', async () => {
    const calls = mockEngine(BASE);
    renderCard();
    expect(await screen.findByText('2 pregão(ões) com pendência, até 19/11/2026.')).toBeInTheDocument();
    expect(screen.getByText('Negócios do ativo-objeto').nextSibling).toHaveTextContent('189');
    expect(screen.getByText('4 min')).toBeInTheDocument();
    expect(screen.getByText('Fonte simulada')).toBeInTheDocument();
    expect(screen.getByText(/Carga inicial/)).toBeInTheDocument();
    expect(new URL(calls[0]!.url).pathname).toBe('/api/engine/collection/pending');
  });

  it('mostra o erro do engine (RFC 9457) quando a coleta não pode começar', async () => {
    mockEngine(BASE);
    renderCard();
    fireEvent.click(await screen.findByRole('button', { name: 'Coletar agora' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Já existe uma coleta em andamento.');
    expect(push).not.toHaveBeenCalled();
  });

  it('com coleta ativa, oferece acompanhar em vez de coletar', async () => {
    mockEngine({
      ...BASE,
      active_run: {
        id: 7, status: 'running', origin: 'manual', reference_date: '2026-11-20', created_at: '2026-11-20T10:00:00Z',
        started_at: null, finished_at: null, message: null, config_version_id: 1,
      },
    });
    renderCard();
    expect(await screen.findByRole('link', { name: 'Acompanhar' })).toHaveAttribute('href', '/app/coleta');
    expect(screen.queryByRole('button', { name: 'Coletar agora' })).not.toBeInTheDocument();
  });

  it('sem pendências, informa até quando está coletado', async () => {
    mockEngine({ ...BASE, pending_days: [], known_requests: 0, days_awaiting_cotahist: 0, is_initial_load: false });
    renderCard();
    expect(await screen.findByText('Tudo coletado até 19/11/2026.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('isCollectionQuery', () => {
  it('reconhece as consultas que dependem da coleta', () => {
    expect(isCollectionQuery([{ _id: 'getCollectionPending' }])).toBe(true);
    expect(isCollectionQuery([{ _id: 'getHealth' }])).toBe(true);
    expect(isCollectionQuery([{ _id: 'listUnderlyings' }])).toBe(false);
    expect(isCollectionQuery(['x'])).toBe(false);
  });
});

describe('contrato', () => {
  it('aceita timestamptz com offset (Postgres em America/Sao_Paulo)', async () => {
    const { zCollectionPendingResponse } = await import('@vollab/api-types/zod');
    const run = {
      id: 1, status: 'running', origin: 'manual', reference_date: '2026-11-20',
      created_at: '2026-11-22T16:40:01.123456-03:00', started_at: null, finished_at: null, message: null,
      config_version_id: 1,
    };
    expect(zCollectionPendingResponse.safeParse({ ...BASE, active_run: run }).success).toBe(true);
  });
});
