'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table';
import type { EstimatedValue, RankingResponse, RankingRow } from '@vollab/api-types';
import { getRankingOptions } from '@vollab/api-types/react-query';
import {
  formatBusinessDays,
  formatDate,
  formatFraction,
  formatMoney,
  formatNumber,
  formatRelative,
  formatSmallRate,
  formatVolPoints,
} from '@/lib/format';
import { NOT_CALIBRATED_HELP, SPREAD_ESTIMATE_HELP, STATE_HELP, stateText } from '@/lib/edge/labels';
import { MODEL_LABEL } from '@/lib/forecast/labels';
import { EVENT_KIND_LABEL } from '@/lib/vol/labels';
import EstimatedValueView from '../vol/EstimatedValueView';
import styles from '../vol/vol.module.css';
import local from './ranking.module.css';

const col = createColumnHelper<RankingRow>();

function sortValue(v: EstimatedValue): number | undefined {
  return v.status === 'ok' && v.value != null ? v.value : undefined;
}

function NotCalibrated({ value }: { value: EstimatedValue }) {
  if (value.calibrated !== false) return null;
  return (
    <span className={styles.tag} title={NOT_CALIBRATED_HELP}>
      não calibrado
    </span>
  );
}

export function StateBadge({ row }: { row: Pick<RankingRow, 'state' | 'direction' | 'reason'> }) {
  return (
    <span className={local.badge} data-state={row.state} title={row.reason ?? STATE_HELP[row.state]}>
      {stateText(row)}
    </span>
  );
}

const columns = [
  col.accessor('position', { header: '#', cell: (c) => formatNumber(c.getValue()), meta: { num: true } }),
  col.accessor('ticker', {
    header: 'Ativo',
    cell: (c) => (
      <Link className={styles.link} href={`/app/ativos/${c.getValue()}`}>
        {c.getValue()}
      </Link>
    ),
  }),
  col.accessor((r) => r.position, {
    id: 'state',
    header: 'Semáforo',
    cell: (c) => <StateBadge row={c.row.original} />,
  }),
  col.accessor((r) => r.net_relative_edge ?? undefined, {
    id: 'net_relative_edge',
    header: 'Edge relativo líquido',
    sortUndefined: 'last',
    cell: (c) => formatRelative(c.row.original.net_relative_edge),
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.relative_edge), {
    id: 'relative_edge',
    header: 'Edge relativo [intervalo]',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.relative_edge} format={formatRelative} showInterval />,
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.premium), {
    id: 'premium',
    header: 'Prêmio [intervalo]',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.premium} format={formatVolPoints} showInterval />,
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.iv), {
    id: 'iv',
    header: 'IV ex-evento',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.iv} />,
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.forecast), {
    id: 'forecast',
    header: 'RV prevista [intervalo]',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.forecast} showInterval />,
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.normal_spread), {
    id: 'normal_spread',
    header: 'Spread normal',
    sortUndefined: 'last',
    cell: (c) => (
      <>
        <EstimatedValueView value={c.row.original.normal_spread} format={formatRelative} />
        <NotCalibrated value={c.row.original.normal_spread} />
      </>
    ),
    meta: { num: true },
  }),
  col.accessor((r) => r.required_sell ?? undefined, {
    id: 'costs',
    header: 'Custos + limiar (venda / compra)',
    sortUndefined: 'last',
    cell: (c) => {
      const r = c.row.original;
      if (r.required_sell == null) return <span className={styles.muted}>—</span>;
      return (
        <>
          {formatVolPoints(r.required_sell)} / {r.required_buy == null ? 'inviável' : formatVolPoints(r.required_buy)}
          <span className={styles.tag} title={SPREAD_ESTIMATE_HELP}>
            estimativa
          </span>
        </>
      );
    },
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.iv_rank), {
    id: 'iv_rank',
    header: 'IV rank',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.iv_rank} format={(v) => formatFraction(v, 0)} />,
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.skew), {
    id: 'skew',
    header: 'Skew',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.skew} format={formatVolPoints} />,
    meta: { num: true },
  }),
  col.accessor((r) => sortValue(r.term_slope.value), {
    id: 'term',
    header: 'Estrutura a termo',
    sortUndefined: 'last',
    cell: (c) => <EstimatedValueView value={c.row.original.term_slope.value} format={formatVolPoints} />,
    meta: { num: true },
  }),
  col.accessor((r) => r.events.length, {
    id: 'events',
    header: 'Eventos',
    cell: (c) =>
      c.row.original.events.length === 0 ? (
        <span className={styles.muted}>—</span>
      ) : (
        c.row.original.events.map((e) => (
          <div key={e.id} className={styles.small}>
            {EVENT_KIND_LABEL[e.kind as keyof typeof EVENT_KIND_LABEL] ?? e.kind} {formatDate(e.event_date)}
            {e.status === 'estimated' && <span className={styles.muted}> (estimado)</span>}
          </div>
        ))
      ),
  }),
  col.accessor((r) => r.liquidity?.option_trades, {
    id: 'liquidity',
    header: 'Liquidez (séries / negócios)',
    sortUndefined: 'last',
    cell: (c) => {
      const l = c.row.original.liquidity;
      return l ? `${formatNumber(l.liquid_series)} / ${formatNumber(l.option_trades)}` : '—';
    },
    meta: { num: true },
  }),
];

/**
 * Ranking de oportunidades (PRD 1.8 §8.1; RF-RNK-01/02, PRD-UI-01): semáforo e número de edge por
 * ativo, com intervalos e os rótulos "não calibrado", "estimativa" e "aproximado".
 */
export default function RankingView() {
  const { data, isPending, isError } = useQuery(getRankingOptions());
  if (isError) return <p className={styles.error}>Não foi possível calcular o ranking. O engine está no ar?</p>;
  if (isPending) return <p className={styles.muted}>Calculando…</p>;
  return <RankingTable data={data} />;
}

export function RankingTable({ data }: { data: RankingResponse }) {
  // O `useReactTable` devolve funções que o React Compiler não memoiza com segurança: este componente
  // fica fora da compilação (no máximo 10 linhas).
  'use no memo';
  const [sorting, setSorting] = useState<SortingState>([]);
  const rows = useMemo(() => data.rows, [data.rows]);
  // eslint-disable-next-line react-hooks/incompatible-library -- fora do compilador pela diretiva acima
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
    getRowId: (r) => r.ticker,
  });
  const threshold = data.rows[0]?.threshold;

  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="rk-title">
      <h2 id="rk-title" className={`${styles.eyebrow} mono`}>
        Ranking
      </h2>
      <p className={styles.muted}>
        Prazo de {formatBusinessDays(data.horizon_bd)}; modelo do edge: <strong>{MODEL_LABEL[data.selected_model]}</strong>;
        intervalo de {formatFraction(data.ci_level, 0)}. Ordem: estado do semáforo, depois edge relativo líquido. Limiar{' '}
        {threshold ? formatVolPoints(threshold.value) : '—'}
        {threshold && <NotCalibrated value={threshold} />}. Configuração v{data.config_version_id}.
      </p>
      {data.rows.length === 0 ? (
        <p className={styles.muted}>Nenhum ativo ativo cadastrado.</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  <th scope="col">
                    <span className="sr-only">Detalhes</span>
                  </th>
                  {hg.headers.map((h) => {
                    const sorted = h.column.getIsSorted();
                    const num = (h.column.columnDef.meta as { num?: boolean } | undefined)?.num;
                    return (
                      <th
                        key={h.id}
                        scope="col"
                        className={num ? styles.num : undefined}
                        aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}
                      >
                        {h.column.getCanSort() ? (
                          <button type="button" className={local.sort} onClick={h.column.getToggleSortingHandler()}>
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            {sorted === 'asc' ? ' ↑' : sorted === 'desc' ? ' ↓' : ''}
                          </button>
                        ) : (
                          flexRender(h.column.columnDef.header, h.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} data-testid={`ranking-row-${row.original.ticker}`}>
                  <td>
                    <button
                      type="button"
                      className={local.expand}
                      aria-expanded={row.getIsExpanded()}
                      aria-label={`Detalhes de ${row.original.ticker}`}
                      onClick={row.getToggleExpandedHandler()}
                    >
                      {row.getIsExpanded() ? '−' : '+'}
                    </button>
                  </td>
                  {row.getVisibleCells().map((cell) => {
                    const num = (cell.column.columnDef.meta as { num?: boolean } | undefined)?.num;
                    return (
                      <td key={cell.id} className={num ? styles.num : undefined}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {/* Detalhes fora da tabela: a tabela rola na horizontal e cortaria o painel. */}
      {table
        .getRowModel()
        .rows.filter((r) => r.getIsExpanded())
        .map((r) => (
          <section
            key={r.id}
            className={local.panel}
            aria-label={`Detalhes de ${r.original.ticker}`}
            data-testid={`ranking-details-${r.original.ticker}`}
          >
            <h3 className={`${styles.eyebrow} mono`}>Detalhes de {r.original.ticker}</h3>
            <RowDetails row={r.original} />
          </section>
        ))}
    </section>
  );
}

export function RowDetails({ row }: { row: RankingRow }) {
  const c = row.costs;
  return (
    <div className={local.details}>
      {row.reason && (
        <p className={row.state === 'unavailable' ? styles.warn : styles.muted}>
          <strong>Motivo:</strong> {row.reason}
        </p>
      )}
      <dl className={local.facts}>
        <dt>Pregão da IV</dt>
        <dd>
          {formatDate(row.as_of)} · prazo {formatBusinessDays(row.horizon_bd)}
          {row.approximate && (
            <span className={styles.tag} title="IV ATM do vencimento disponível, sem prazo constante (RN-VOL-05).">
              aproximado
            </span>
          )}
        </dd>
        <dt>IV com eventos</dt>
        <dd>
          <EstimatedValueView value={row.iv_with_events} />
        </dd>
        <dt>Spread normal</dt>
        <dd>
          <EstimatedValueView value={row.normal_spread} format={formatRelative} showInterval />{' '}
          <NotCalibrated value={row.normal_spread} /> ({formatNumber(row.normal_spread_pairs)} janelas)
        </dd>
        <dt>Prêmio líquido na direção</dt>
        <dd>{row.net_premium == null ? '—' : formatVolPoints(row.net_premium)}</dd>
        <dt>P&amp;L esperado por straddle de referência</dt>
        <dd>
          {formatMoney(row.expected_pnl_brl)} <span className={styles.muted}>(≈ vega × pontos líquidos)</span>
        </dd>
      </dl>
      {c ? (
        <>
          <h3 className={`${styles.eyebrow} mono`}>Custos (straddle ATM de referência, ida e volta)</h3>
          <dl className={local.facts}>
            <dt>Spread das opções ATM</dt>
            <dd>
              {formatSmallRate(c.option_spread_central)} central · {formatSmallRate(c.option_spread_conservative)}{' '}
              conservador ({formatNumber(c.spread_days)} pregões, {formatNumber(c.spread_series)} séries)
              <span className={styles.tag} title={SPREAD_ESTIMATE_HELP}>
                estimativa
              </span>
              {c.option_spread_quoted != null && (
                <span className={styles.muted}> · fechamento COTAHIST (conferência): {formatSmallRate(c.option_spread_quoted)}</span>
              )}
            </dd>
            <dt>Prêmio e vega do straddle</dt>
            <dd>
              {formatMoney(c.straddle_premium_brl)} · vega {formatMoney(c.straddle_vega_brl, 4)} por ponto
            </dd>
            <dt>Opções</dt>
            <dd>
              spread {formatMoney(c.spread_brl)} + taxas {formatMoney(c.fees_brl)} + corretagem {formatMoney(c.brokerage_brl)} ={' '}
              {formatVolPoints(c.options_vol_pts, 2)}
            </dd>
            <dt>Hedge (Leland, a cada {formatBusinessDays(c.hedge_interval_bd)})</dt>
            <dd>
              venda {formatVolPoints(c.hedge_sell_vol_pts, 2)} · compra{' '}
              {c.hedge_buy_vol_pts == null ? 'inviável' : formatVolPoints(c.hedge_buy_vol_pts, 2)} · λ{' '}
              {formatSmallRate(c.hedge_half_spread)}
              {!c.underlying_spread_estimated && <span className={styles.muted}> (spread do ativo = piso de um tick)</span>}
            </dd>
            <dt>Total</dt>
            <dd>
              venda {formatVolPoints(c.total_sell_vol_pts, 2)} · compra{' '}
              {c.total_buy_vol_pts == null ? 'inviável' : formatVolPoints(c.total_buy_vol_pts, 2)} · mais o limiar{' '}
              {formatVolPoints(row.threshold.value)}
            </dd>
          </dl>
        </>
      ) : (
        <p className={styles.muted}>Custos indisponíveis.</p>
      )}
    </div>
  );
}
