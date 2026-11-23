'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  getEventJumpsOptions,
  getUnderlyingSeriesOptions,
  getUnderlyingSummaryOptions,
} from '@vollab/api-types/react-query';
import {
  formatBusinessDays,
  formatDate,
  formatDateTime,
  formatFraction,
  formatMoney,
  formatNumber,
  formatReturn,
} from '@/lib/format';
import EstimatedValueView from './EstimatedValueView';
import styles from './vol.module.css';

/** Cabeçalho: último pregão, qualidade do intradiário e da sincronização da IV (RN-VOL-03/08). */
export function AssetSummary({ ticker }: { ticker: string }) {
  const { data, isError } = useQuery(getUnderlyingSummaryOptions({ path: { ticker } }));
  if (isError) return <p className={styles.error}>Não foi possível carregar o ativo. O engine está no ar?</p>;
  if (!data) return <p className={styles.muted}>Carregando…</p>;
  const stale = data.as_of != null && data.as_of < data.expected_as_of;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="summary-title">
      <h2 id="summary-title" className={`${styles.eyebrow} mono`}>
        Dados
      </h2>
      <dl className={styles.facts}>
        <div>
          <dt>Fechamento oficial</dt>
          <dd className={styles.headline}>{formatMoney(data.close)}</dd>
        </div>
        <div>
          <dt>Último pregão</dt>
          <dd>
            {formatDate(data.as_of)}
            {stale && (
              <span className={styles.tag} title={`O último pregão esperado é ${formatDate(data.expected_as_of)}.`}>
                desatualizado
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>Intradiário ({formatDate(data.intraday?.trade_date)})</dt>
          <dd>
            {data.intraday ? (
              <>
                {formatFraction(data.intraday.coverage)} das barras de 5 min com negócio
                {!data.intraday.complete && <span className={styles.tag}>incompleto</span>}
              </>
            ) : (
              <span className={styles.muted}>sem negócios intradiários</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Sincronização da IV ({formatDate(data.iv_quality?.trade_date)})</dt>
          <dd>
            {data.iv_quality ? (
              <>
                {formatNumber(data.iv_quality.trades_synced)} de {formatNumber(data.iv_quality.trades_valid)} negócios
                sincronizados; {formatNumber(data.iv_quality.trades_lag_discarded)} descartados (defasagem acima de{' '}
                {formatNumber(data.iv_quality.sync_window_s)} s); {formatNumber(data.iv_quality.trades_no_solution)} sem
                IV
              </>
            ) : (
              <span className={styles.muted}>sem negócios de opções</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Último recálculo</dt>
          <dd>{data.computed_at ? formatDateTime(data.computed_at) : <span className={styles.muted}>nenhum</span>}</dd>
        </div>
      </dl>
    </section>
  );
}

/** Salto dos eventos futuros: estrutura a termo × histórico (RN-EVT-01/02). */
export function EventJumpsCard({ ticker }: { ticker: string }) {
  const { data, isError } = useQuery(getEventJumpsOptions({ path: { ticker } }));
  return (
    <section className={styles.card} aria-labelledby="jumps-title">
      <h2 id="jumps-title" className={`${styles.eyebrow} mono`}>
        Salto de eventos (resultados)
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar os saltos.</p>}
      {data && data.jumps.length === 0 && (
        <p className={styles.muted}>
          Nenhum resultado futuro cadastrado. Cadastre em <Link className={styles.link} href="/app/eventos">
            Eventos
          </Link>.
        </p>
      )}
      {data && data.jumps.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Data</th>
                <th scope="col" className={styles.num}>
                  Salto (σ do dia)
                </th>
                <th scope="col" className={styles.num}>
                  Movimento esperado
                </th>
                <th scope="col" className={styles.num}>
                  Histórico
                </th>
              </tr>
            </thead>
            <tbody>
              {data.jumps.map((j) => (
                <tr key={j.event.id}>
                  <td>
                    {formatDate(j.event.event_date)}
                    {j.event.status === 'estimated' && <span className={styles.tag}>data estimada</span>}
                  </td>
                  <td className={styles.num}>
                    <EstimatedValueView value={j.jump} format={formatReturn} showInterval />
                  </td>
                  <td className={styles.num}>{formatReturn(j.expected_move)}</td>
                  <td className={styles.num}>
                    {j.historical_n > 0 ? (
                      <>
                        {formatReturn(j.historical_value)}{' '}
                        <span className={styles.muted}>(n = {formatNumber(j.historical_n)})</span>
                      </>
                    ) : (
                      <span className={styles.muted}>sem histórico</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.jumps.some((j) => j.term_structure_reason) && (
            <p className={`${styles.muted} ${styles.small}`}>
              Estrutura a termo: {data.jumps.find((j) => j.term_structure_reason)?.term_structure_reason}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/** Séries do último pregão com a IV de referência (RN-VOL-04/06). */
export function SeriesCard({ ticker }: { ticker: string }) {
  const { data, isError } = useQuery(getUnderlyingSeriesOptions({ path: { ticker } }));
  const [showAll, setShowAll] = useState(false);
  const traded = data?.series.filter((s) => s.trades_count > 0) ?? [];
  // Padrão: só as séries com negócios intradiários coletados (as elegíveis da coleta, QA-06).
  const collected = traded.filter((s) => s.iv != null);
  const rows = showAll ? traded : collected;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="series-title">
      <h2 id="series-title" className={`${styles.eyebrow} mono`}>
        Séries com negócios em {formatDate(data?.as_of)}
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar as séries.</p>}
      <div className={styles.controls}>
        <span className={styles.muted}>
          {formatNumber(collected.length)} com negócios coletados de {formatNumber(traded.length)} com negócios no
          COTAHIST.
        </span>
        {traded.length > collected.length && (
          <button type="button" className={styles.ghost} onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Só as coletadas' : 'Mostrar todas'}
          </button>
        )}
      </div>
      {data && rows.length === 0 && <p className={styles.muted}>Nenhuma série com negócios coletados no pregão.</p>}
      {rows.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Série</th>
                <th scope="col">Tipo</th>
                <th scope="col">Vencimento</th>
                <th scope="col" className={styles.num}>
                  Strike
                </th>
                <th scope="col" className={styles.num}>
                  Negócios
                </th>
                <th scope="col" className={styles.num}>
                  IV de referência
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={`${s.code}:${s.expiry}`}>
                  <td className="mono">
                    {s.code}
                    {!s.liquid && (
                      <span className={styles.tag} title="Abaixo do filtro de liquidez: fora do smile e da ATM.">
                        ilíquida
                      </span>
                    )}
                  </td>
                  <td>
                    {s.option_type === 'call' ? 'Call' : 'Put'} {s.style === 'european' ? 'europeia' : 'americana'}
                  </td>
                  <td>
                    {formatDate(s.expiry)} <span className={styles.muted}>({formatBusinessDays(s.days_to_expiry_bd)})</span>
                  </td>
                  <td className={styles.num}>{formatMoney(s.strike)}</td>
                  <td className={styles.num}>{formatNumber(s.trades_count)}</td>
                  <td className={styles.num}>
                    {s.iv ? (
                      <>
                        <EstimatedValueView value={s.iv} />
                        {s.iv_status === 'low_sample' && <span className={styles.tag}>baixa amostra</span>}
                      </>
                    ) : (
                      <span className={styles.muted}>não coletada</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
