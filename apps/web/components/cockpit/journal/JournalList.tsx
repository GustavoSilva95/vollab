'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table';
import type { PositionSummary } from '@vollab/api-types';
import { listPositionsOptions } from '@vollab/api-types/react-query';
import { formatDate, formatDateTime, formatFraction, formatMoney, formatNumber } from '@/lib/format';
import { STATE_LABEL } from '@/lib/edge/labels';
import { CS04_HELP, ERROR_FLAG_HELP, STATUS_LABEL } from '@/lib/journal/labels';
import { STRUCTURE_LABEL } from '@/lib/simulator/labels';
import styles from '../vol/vol.module.css';
import local from '../ranking/ranking.module.css';

const col = createColumnHelper<PositionSummary>();

const columns = [
  col.accessor('id', {
    header: 'Operação',
    cell: (c) => (
      <Link className={styles.link} href={`/app/operacoes/${c.getValue()}`}>
        #{formatNumber(c.getValue())}
      </Link>
    ),
  }),
  col.accessor('status', { header: 'Status', cell: (c) => STATUS_LABEL[c.getValue()] }),
  col.accessor('ticker', { header: 'Ativo' }),
  col.accessor('structure', { header: 'Estrutura', cell: (c) => STRUCTURE_LABEL[c.getValue()] }),
  col.accessor('lots', { header: 'Lotes', cell: (c) => formatNumber(c.getValue()), meta: { num: true } }),
  col.accessor('expiry', { header: 'Vencimento', cell: (c) => formatDate(c.getValue()) }),
  col.accessor('created_at', { header: 'Registrada em', cell: (c) => formatDateTime(c.getValue()) }),
  col.accessor('edge_state', {
    header: 'Semáforo na entrada',
    cell: (c) => (
      <>
        {STATE_LABEL[c.getValue()]}
        {c.row.original.overridden && <span className={styles.tag}>override</span>}
      </>
    ),
  }),
  col.accessor((r) => (r.pnl_total_brl == null ? undefined : Number(r.pnl_total_brl)), {
    id: 'pnl',
    header: 'P&L acumulado',
    cell: (c) => formatMoney(c.row.original.pnl_total_brl),
    meta: { num: true },
    sortUndefined: 'last',
  }),
  col.accessor('last_mark_date', { header: 'Última marcação', cell: (c) => formatDate(c.getValue()) }),
  col.accessor((r) => r.cs04_ratio ?? undefined, {
    id: 'cs04',
    header: 'Resíduo (CS-04)',
    cell: (c) => {
      const r = c.row.original.cs04_ratio;
      if (r == null) return '—';
      return (
        <span title={CS04_HELP} className={r >= 0.15 ? styles.warn : undefined}>
          {formatFraction(Math.min(r, 1))}
          {r > 1 ? '+' : ''}
        </span>
      );
    },
    meta: { num: true },
    sortUndefined: 'last',
  }),
  col.display({
    id: 'alerts',
    header: 'Avisos',
    cell: (c) => {
      const p = c.row.original;
      return (
        <>
          {p.ledger_error && (
            <span className={styles.tag} title={p.ledger_error}>
              lançamentos inconsistentes
            </span>
          )}
          {p.error_days > 0 && (
            <span className={styles.tag} title={ERROR_FLAG_HELP}>
              {formatNumber(p.error_days)} dia(s) com resíduo alto
            </span>
          )}
          {p.pending_expiry.length > 0 && (
            <span className={styles.tag} title="Lance exercício, designação ou vencimento sem exercício (LC-08).">
              vencida: {p.pending_expiry.join(', ')}
            </span>
          )}
          {p.rolled_from_position_id != null && <span className={styles.tag}>rolada de #{p.rolled_from_position_id}</span>}
        </>
      );
    },
  }),
];

/** Diário (PRD 1.10 §8.1): lista das operações com o status derivado dos lançamentos. */
export default function JournalList() {
  const { data, isPending, isError } = useQuery(listPositionsOptions());
  if (isError) return <p className={styles.error}>Não foi possível ler o diário. O engine está no ar?</p>;
  if (isPending) return <p className={styles.muted}>Carregando…</p>;
  return <JournalTable rows={data} />;
}

export function JournalTable({ rows }: { rows: PositionSummary[] }) {
  // Mesma diretiva do ranking: o `useReactTable` fica fora do React Compiler.
  'use no memo';
  const [sorting, setSorting] = useState<SortingState>([]);
  // eslint-disable-next-line react-hooks/incompatible-library -- fora do compilador pela diretiva acima
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (r) => String(r.id),
  });
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="dj-title">
      <h2 id="dj-title" className={`${styles.eyebrow} mono`}>
        Operações
      </h2>
      {rows.length === 0 ? (
        <p className={styles.muted}>
          Nenhuma operação registrada. As entradas nascem no <Link href="/app/simulador">simulador</Link>, com o semáforo.
        </p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
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
                <tr key={row.id} data-testid={`journal-row-${row.original.id}`}>
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
    </section>
  );
}
