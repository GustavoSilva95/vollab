'use client';

import { memo, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { CollectionGapsResponse, CollectionRunResponse, RunSummary } from '@vollab/api-types';
import {
  getCollectionGapsOptions,
  getCollectionPendingOptions,
  getCollectionRunOptions,
} from '@vollab/api-types/react-query';
import { formatDate, formatDateTime, formatDuration, formatNumber, formatShare } from '@/lib/format';
import {
  GAP_LABELS,
  GROUP_LABELS,
  GROUP_ORDER,
  RUN_STATUS_LABELS,
  RUN_STATUS_TONE,
  isActive,
} from '@/lib/collection/labels';
import { isCollectionQuery, useStartCollection } from '@/lib/collection/useStartCollection';
import styles from './collection.module.css';

/**
 * Tela de coleta (PRD §8.1 `/app/coleta`): execução, progresso ao vivo (polling) e relatório
 * de falhas e lacunas por ativo e data (RF-DAD-06).
 */
export default function CollectionMonitor() {
  const queryClient = useQueryClient();
  const pending = useQuery({
    ...getCollectionPendingOptions(),
    // O progresso vem de /runs/{id} a cada 2 s; /pending (replaneja) só de vez em quando.
    refetchInterval: (query) => (isActive(query.state.data?.active_run) ? 30_000 : false),
  });
  const [startedId, setStartedId] = useState<number | null>(null);
  const runSummary: RunSummary | null = pending.data?.active_run ?? pending.data?.last_run ?? null;
  const runId = startedId ?? runSummary?.id ?? null;

  const run = useQuery({
    ...getCollectionRunOptions({ path: { run_id: runId ?? 0 } }),
    enabled: runId != null,
    refetchInterval: (query) => (isActive(query.state.data?.run) ? 2_000 : false),
  });

  // Ao terminar uma coleta, atualiza pendências, lacunas e o estado do engine.
  const wasActive = useRef(false);
  const runActive = isActive(run.data?.run);
  useEffect(() => {
    if (wasActive.current && !runActive) {
      queryClient.invalidateQueries({ predicate: (q) => isCollectionQuery(q.queryKey) });
    }
    wasActive.current = runActive;
  }, [runActive, queryClient]);

  const { start, isStarting, errorMessage } = useStartCollection((id) => setStartedId(id));
  const activeNow = isActive(run.data?.run) || isActive(pending.data?.active_run);
  const canStart = !activeNow && pending.data != null && pending.data.known_requests + pending.data.days_awaiting_cotahist > 0;

  return (
    <div className={styles.stack}>
      <section className={styles.card} aria-labelledby="run-title">
        <h2 id="run-title" className={`${styles.eyebrow} mono`}>
          {activeNow ? 'Coleta em andamento' : 'Última coleta'}
        </h2>
        {pending.isError && !pending.data && <p className={styles.muted}>Não foi possível falar com o engine.</p>}
        {pending.data && runId == null && <p className={styles.muted}>Nenhuma coleta foi feita ainda.</p>}
        {run.data && <RunProgress data={run.data} />}
        {pending.data?.data_source === 'fixtures' && (
          <p className={styles.row}>
            <span className={styles.badge}>Fonte simulada</span>
          </p>
        )}
        <div className={styles.row}>
          {canStart && (
            <button type="button" className={styles.button} onClick={start} disabled={isStarting}>
              {isStarting ? 'Iniciando…' : run.data?.run.status === 'interrupted' ? 'Retomar coleta' : 'Coletar agora'}
            </button>
          )}
          {pending.data && !activeNow && (
            <span className={styles.muted}>
              {canStart
                ? `Pendentes: ${formatNumber(pending.data.known_requests)} requisição(ões) conhecidas, até ${formatDate(pending.data.reference_date)}.`
                : `Tudo coletado até ${formatDate(pending.data.reference_date)}.`}
            </span>
          )}
        </div>
        {errorMessage && (
          <p className={styles.error} role="alert">
            {errorMessage}
          </p>
        )}
      </section>

      <GapReport />
    </div>
  );
}

function RunProgress({ data }: { data: CollectionRunResponse }) {
  const { run, totals } = data;
  const done = totals.total - totals.pending;
  const tone = RUN_STATUS_TONE[run.status];
  return (
    <>
      <p className={styles.status} data-tone={tone} role="status" aria-live="polite">
        <span className={styles.dot} aria-hidden="true" />
        {RUN_STATUS_LABELS[run.status]}
        {run.origin === 'initial_load' && <span className={styles.muted}>· carga inicial</span>}
      </p>
      {run.message && <p className={`${styles.muted} ${styles.row}`}>{run.message}</p>}
      <div
        className={styles.bar}
        role="progressbar"
        aria-label="Progresso da coleta"
        aria-valuemin={0}
        aria-valuemax={totals.total}
        aria-valuenow={done}
      >
        <div className={styles.barFill} style={{ width: totals.total ? `${(done / totals.total) * 100}%` : '0%' }} />
      </div>
      <dl className={styles.counts}>
        <div>
          <dt>Itens processados</dt>
          <dd className="mono">
            {formatNumber(done)} de {formatNumber(totals.total)} ({formatShare(done, totals.total)})
          </dd>
        </div>
        <div>
          <dt>Com dados · vazios · com falha</dt>
          <dd className="mono">
            {formatNumber(totals.ok)} · {formatNumber(totals.empty)} · {formatNumber(totals.failed)}
          </dd>
        </div>
        {isActive(run) && (
          <div>
            <dt>Tempo restante estimado</dt>
            <dd className="mono">{formatDuration(data.estimated_seconds_remaining)}</dd>
          </div>
        )}
        {data.current && (
          <div>
            <dt>Agora</dt>
            <dd className="mono">
              {GROUP_LABELS[data.current.group]}: {data.current.key === '-' ? '' : `${data.current.key} · `}
              {formatDate(data.current.trade_date)}
            </dd>
          </div>
        )}
        <div>
          <dt>Início · fim</dt>
          <dd className="mono">
            {formatDateTime(run.started_at)} · {formatDateTime(run.finished_at)}
          </dd>
        </div>
      </dl>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className={styles.srOnly}>Itens por grupo</caption>
          <thead>
            <tr>
              <th scope="col">Grupo</th>
              <th scope="col" className={styles.num}>Total</th>
              <th scope="col" className={styles.num}>Pendentes</th>
              <th scope="col" className={styles.num}>Com dados</th>
              <th scope="col" className={styles.num}>Vazios</th>
              <th scope="col" className={styles.num}>Falhas</th>
            </tr>
          </thead>
          <tbody>
            {GROUP_ORDER.flatMap((name) => data.groups.filter((g) => g.group === name && g.total > 0)).map(
              (g) => (
                <tr key={g.group}>
                  <th scope="row">{GROUP_LABELS[g.group]}</th>
                  <td className={styles.num}>{formatNumber(g.total)}</td>
                  <td className={styles.num}>{formatNumber(g.pending)}</td>
                  <td className={styles.num}>{formatNumber(g.ok)}</td>
                  <td className={styles.num}>{formatNumber(g.empty)}</td>
                  <td className={styles.num}>{formatNumber(g.failed)}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// memo: não re-renderiza as ~600 linhas a cada atualização do progresso (2 s).
const GapReport = memo(function GapReport() {
  const { data, isError, isPending } = useQuery(getCollectionGapsOptions({ query: { limit: 300 } }));
  return (
    <section className={styles.card} aria-labelledby="gaps-title" aria-busy={isPending}>
      <h2 id="gaps-title" className={`${styles.eyebrow} mono`}>
        Relatório de falhas e lacunas
      </h2>
      {isError && <p className={styles.muted}>Não foi possível carregar o relatório.</p>}
      {data && <GapBody data={data} />}
    </section>
  );
});

function GapBody({ data }: { data: CollectionGapsResponse }) {
  if (data.gaps_total === 0 && data.failures_total === 0) {
    return (
      <p className={styles.headline}>
        Sem lacunas entre {formatDate(data.bars_start)} e {formatDate(data.reference_date)}.
      </p>
    );
  }
  return (
    <>
      <p className={styles.muted}>
        OHLC oficial de {formatDate(data.bars_start)} a {formatDate(data.reference_date)}; negócios
        intradiários desde {formatDate(data.intraday_start)}.
      </p>
      <ul className={styles.chips} aria-label="Resumo por tipo">
        {data.summary.map((s) => (
          <li key={s.kind} className={styles.chip}>
            {GAP_LABELS[s.kind]}: <span className="mono">{formatNumber(s.count)}</span>
          </li>
        ))}
      </ul>
      {data.gaps.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className={styles.srOnly}>Lacunas por ativo e data</caption>
            <thead>
              <tr>
                <th scope="col">Pregão</th>
                <th scope="col">Ativo</th>
                <th scope="col">Tipo</th>
                <th scope="col">Detalhe</th>
                <th scope="col" className={styles.num}>Qtd.</th>
              </tr>
            </thead>
            <tbody>
              {data.gaps.map((g) => (
                <tr key={`${g.trade_date}-${g.underlying ?? '-'}-${g.kind}`}>
                  <td className="mono">{formatDate(g.trade_date)}</td>
                  <td className="mono">{g.underlying ?? 'todos'}</td>
                  <td>{GAP_LABELS[g.kind]}</td>
                  <td>{g.detail}</td>
                  <td className={styles.num}>{formatNumber(g.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.gaps_total > data.gaps.length && (
            <p className={styles.muted}>
              Mostrando {formatNumber(data.gaps.length)} de {formatNumber(data.gaps_total)} lacunas (as mais recentes).
            </p>
          )}
        </div>
      )}
      {data.failures.length > 0 && (
        <details className={styles.row}>
          <summary>
            Itens com falha ({formatNumber(data.failures_total)})
          </summary>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Pregão</th>
                  <th scope="col">Fonte</th>
                  <th scope="col">Item</th>
                  <th scope="col">Erro</th>
                  <th scope="col">Nova tentativa</th>
                </tr>
              </thead>
              <tbody>
                {data.failures.map((f) => (
                  <tr key={`${f.source}-${f.key}-${f.trade_date}`}>
                    <td className="mono">{formatDate(f.trade_date)}</td>
                    <td>{GROUP_LABELS[f.group]}</td>
                    <td className="mono">{f.key}</td>
                    <td>{f.error}</td>
                    <td>{f.permanent ? 'não (definitiva)' : 'na próxima coleta'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </>
  );
}
