'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Data } from 'plotly.js';
import type { ConstantMaturityResponse, SmileResponse, TermStructureResponse } from '@vollab/api-types';
import {
  getConstantMaturityOptions,
  getSmileOptions,
  getTermStructureOptions,
} from '@vollab/api-types/react-query';
import Plot from '@/lib/charts/Plot';
import { CHART_COLORS } from '@/lib/charts/theme';
import {
  CHART_DATE_HOVERFORMAT,
  CHART_DATE_TICKFORMAT,
  CHART_RATIO_TICKFORMAT,
  CHART_VOL_HOVERFORMAT,
  CHART_VOL_TICKFORMAT_FINE,
  formatBusinessDays,
  formatDate,
  formatMoney,
  formatNumber,
  formatVol,
} from '@/lib/format';
import EstimatedValueView from './EstimatedValueView';
import styles from './vol.module.css';

const VOL_AXIS = { tickformat: CHART_VOL_TICKFORMAT_FINE, hoverformat: CHART_VOL_HOVERFORMAT };

/** IV de prazo constante (com e sem salto de evento), estrutura a termo e smile (RF-VOL-03/05). */
export default function ImpliedPanel({ ticker }: { ticker: string }) {
  return (
    <>
      <ConstantMaturityCard ticker={ticker} />
      <SmileCard ticker={ticker} />
      <TermStructureCard ticker={ticker} />
    </>
  );
}

function ConstantMaturityCard({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(getConstantMaturityOptions({ path: { ticker } }));
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="cm-title" aria-busy={isPending}>
      <h2 id="cm-title" className={`${styles.eyebrow} mono`}>
        IV ATM de prazo constante
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar a IV de prazo constante.</p>}
      {data && !data.latest && <p className={styles.muted}>Sem IV calculada ainda.</p>}
      {data?.latest && <ConstantMaturityBody data={data} />}
    </section>
  );
}

function ConstantMaturityBody({ data }: { data: ConstantMaturityResponse }) {
  const latest = data.latest!;
  const traces = useMemo<Data[]>(
    () => [
      {
        type: 'scatter',
        mode: 'lines+markers',
        name: 'IV de prazo constante',
        x: data.history.map((p) => p.as_of),
        y: data.history.map((p) => p.iv.value ?? null),
        connectgaps: false,
        line: { color: CHART_COLORS.accent },
      },
      {
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Ex-evento',
        x: data.history.map((p) => p.as_of),
        y: data.history.map((p) => p.iv_ex_event.value ?? null),
        connectgaps: false,
        line: { color: CHART_COLORS.warn, dash: 'dot' },
      },
      {
        type: 'scatter',
        mode: 'markers',
        name: 'ATM do vencimento disponível (prazo efetivo)',
        x: data.history.map((p) => p.as_of),
        y: data.history.map((p) => (p.iv.value == null ? (p.fallback_iv ?? null) : null)),
        marker: { color: CHART_COLORS.muted, symbol: 'circle-open', size: 8 },
      },
    ],
    [data],
  );
  return (
    <>
      <dl className={styles.facts}>
        <div>
          <dt>Prazo ({formatBusinessDays(data.target_bd)}), em {formatDate(latest.as_of)}</dt>
          <dd className={styles.headline}>
            <EstimatedValueView value={latest.iv} />
          </dd>
        </div>
        <div>
          <dt>Sem salto de evento (usada na comparação IV × RV)</dt>
          <dd className={styles.headline}>
            <EstimatedValueView value={latest.iv_ex_event} />
          </dd>
        </div>
        {latest.iv.status !== 'ok' && latest.fallback_iv != null && (
          <div>
            <dt>
              ATM do vencimento disponível: {formatDate(latest.fallback_expiry)}, prazo efetivo{' '}
              {formatBusinessDays(latest.fallback_bd)}
            </dt>
            <dd className={styles.headline}>
              {formatVol(latest.fallback_iv)}
              <span className={styles.tag} title="Sem dois vencimentos para interpolar: não há extrapolação (RN-VOL-05).">
                prazo efetivo
              </span>
            </dd>
          </div>
        )}
      </dl>
      {latest.events_removed.length > 0 && (
        <p className={`${styles.muted} ${styles.small}`}>
          Salto removido de {formatNumber(latest.events_removed.length)} evento(s) até o vencimento.
        </p>
      )}
      <Plot
        data={traces}
        layout={{
          xaxis: {
            type: 'date',
            tickformat: CHART_DATE_TICKFORMAT,
            hoverformat: CHART_DATE_HOVERFORMAT,
            // Poucos pregões: um rótulo por dia, sem repetir a data.
            nticks: Math.min(10, data.history.length),
          },
          yaxis: VOL_AXIS,
        }}
        height={280}
        ariaLabel="Histórico da IV ATM de prazo constante, com e sem salto de evento"
      />
    </>
  );
}

function TermStructureCard({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(getTermStructureOptions({ path: { ticker } }));
  return (
    <section className={styles.card} aria-labelledby="ts-title" aria-busy={isPending}>
      <h2 id="ts-title" className={`${styles.eyebrow} mono`}>
        Estrutura a termo (IV ATM)
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar a estrutura a termo.</p>}
      {data && data.points.length === 0 && <p className={styles.muted}>Sem IV ATM calculada ainda.</p>}
      {data && data.points.length > 0 && <TermBody data={data} />}
    </section>
  );
}

function TermBody({ data }: { data: TermStructureResponse }) {
  const ok = data.points.filter((p) => p.atm_iv.status === 'ok');
  return (
    <>
      <p className={styles.muted}>Em {formatDate(data.as_of)}.</p>
      {ok.length > 1 && (
        <Plot
          data={[
            {
              type: 'scatter',
              mode: 'lines+markers',
              x: ok.map((p) => p.days_to_expiry_bd),
              y: ok.map((p) => p.atm_iv.value ?? null),
              line: { color: CHART_COLORS.accent },
              name: 'IV ATM',
            },
          ]}
          layout={{ xaxis: { title: { text: 'dias úteis' } }, yaxis: VOL_AXIS, hovermode: 'closest' }}
          height={220}
          ariaLabel="Estrutura a termo da IV ATM por prazo"
        />
      )}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Vencimento</th>
              <th scope="col" className={styles.num}>
                Prazo
              </th>
              <th scope="col" className={styles.num}>
                IV ATM
              </th>
            </tr>
          </thead>
          <tbody>
            {data.points.map((p) => (
              <tr key={p.expiry}>
                <td>
                  {formatDate(p.expiry)}
                  {p.is_weekly && <span className={styles.tag}>semanal</span>}
                </td>
                <td className={styles.num}>{formatBusinessDays(p.days_to_expiry_bd)}</td>
                <td className={styles.num}>
                  <EstimatedValueView value={p.atm_iv} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SmileCard({ ticker }: { ticker: string }) {
  const [expiry, setExpiry] = useState<string | null>(null);
  const { data, isPending, isError } = useQuery(
    getSmileOptions({ path: { ticker }, query: expiry ? { expiry } : undefined }),
  );
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="smile-title" aria-busy={isPending}>
      <h2 id="smile-title" className={`${styles.eyebrow} mono`}>
        Smile
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar o smile.</p>}
      {data && data.expiries.length === 0 && (
        <p className={styles.muted}>Sem IV de séries líquidas ainda (RN-VOL-04).</p>
      )}
      {data && data.expiries.length > 0 && <SmileBody data={data} onExpiry={setExpiry} />}
    </section>
  );
}

function SmileBody({ data, onExpiry }: { data: SmileResponse; onExpiry: (e: string) => void }) {
  const traces = useMemo<Data[]>(() => {
    const series = (type: 'call' | 'put', color: string): Data => {
      const pts = data.points.filter((p) => p.option_type === type);
      return {
        type: 'scatter',
        mode: 'markers',
        name: type === 'call' ? 'Calls' : 'Puts',
        x: pts.map((p) => p.moneyness),
        y: pts.map((p) => p.iv),
        text: pts.map((p) => p.code),
        marker: {
          color,
          size: 9,
          // Baixa amostra (RN-VOL-06): marcador vazado.
          symbol: pts.map((p) => (p.status === 'low_sample' ? 'circle-open' : 'circle')),
        },
        hovertemplate: '%{text}<br>K/F %{x}<br>IV %{y}<extra></extra>',
      };
    };
    return [series('call', CHART_COLORS.accent), series('put', CHART_COLORS.warn)];
  }, [data]);
  return (
    <>
      <div className={styles.controls}>
        <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          Vencimento
          <select className={styles.select} value={data.expiry ?? ''} onChange={(e) => onExpiry(e.target.value)}>
            {data.expiries.map((e) => (
              <option key={e} value={e}>
                {formatDate(e)}
              </option>
            ))}
          </select>
        </label>
        <span className={styles.muted}>
          {formatBusinessDays(data.days_to_expiry_bd)} · forward {formatMoney(data.forward)} · ATM{' '}
          <EstimatedValueView value={data.atm_iv} />
        </span>
      </div>
      <Plot
        data={traces}
        layout={{
          xaxis: { title: { text: 'K efetivo / forward' }, tickformat: CHART_RATIO_TICKFORMAT },
          yaxis: VOL_AXIS,
          hovermode: 'closest',
        }}
        height={260}
        ariaLabel="Smile: IV por moneyness no vencimento escolhido"
      />
      <p className={`${styles.muted} ${styles.small}`}>
        Só séries líquidas; marcador vazado = baixa amostra (IV do último negócio sincronizado). Moneyness pelo strike
        efetivo no vencimento (com a proteção de proventos da B3).
      </p>
    </>
  );
}
