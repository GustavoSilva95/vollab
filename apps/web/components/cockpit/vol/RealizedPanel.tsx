'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Data } from 'plotly.js';
import type { EstimatorSeries, RealizedVolResponse } from '@vollab/api-types';
import { getRealizedVolOptions } from '@vollab/api-types/react-query';
import Plot from '@/lib/charts/Plot';
import { CHART_COLORS } from '@/lib/charts/theme';
import {
  CHART_DATE_HOVERFORMAT,
  CHART_DATE_TICKFORMAT,
  CHART_VOL_HOVERFORMAT,
  CHART_VOL_TICKFORMAT,
  formatBusinessDays,
  formatDate,
} from '@/lib/format';
import { ESTIMATORS, ESTIMATOR_LABEL, type EstimatorName } from '@/lib/vol/labels';
import EstimatedValueView from './EstimatedValueView';
import styles from './vol.module.css';

/**
 * RV pelos estimadores do livro-base, lado a lado, com a hipótese de cada um (RF-VOL-01, RN-VOL-09).
 * Pregões sem número (dados insuficientes) quebram a linha (PRD-UI-05).
 */
export default function RealizedPanel({ ticker }: { ticker: string }) {
  const { data, isPending, isError } = useQuery(getRealizedVolOptions({ path: { ticker } }));

  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="rv-title" aria-busy={isPending}>
      <h2 id="rv-title" className={`${styles.eyebrow} mono`}>
        Volatilidade realizada
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar a RV.</p>}
      {data && data.estimators.length === 0 && (
        <p className={styles.muted}>Sem RV calculada ainda: rode a coleta; o worker calcula em seguida.</p>
      )}
      {data && data.estimators.length > 0 && <RealizedBody data={data} />}
    </section>
  );
}

function RealizedBody({ data }: { data: RealizedVolResponse }) {
  const [windowBd, setWindowBd] = useState<number>(data.windows_bd[0] ?? 20);
  const byKey = useMemo(() => {
    const m = new Map<string, EstimatorSeries>();
    for (const e of data.estimators) m.set(`${e.estimator}:${e.window_bd}`, e);
    return m;
  }, [data]);
  const asOf = data.estimators.find((e) => e.latest)?.latest.as_of;

  return (
    <>
      <p className={styles.muted}>
        Em {formatDate(asOf)}. Vol anualizada em base 252. O close-to-close oficial é o de{' '}
        {data.official_close_to_close === 'close_to_close' ? 'média zero' : 'média subtraída'}; a vol exibida do
        close-to-close tem correção de viés. O edge usa sempre a previsão escolhida, nunca um estimador cru.
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Estimador</th>
              {data.windows_bd.map((w) => (
                <th key={w} scope="col" className={styles.num}>
                  {formatBusinessDays(w)}
                </th>
              ))}
              <th scope="col">Hipótese</th>
            </tr>
          </thead>
          <tbody>
            {ESTIMATORS.map((e) => {
              const any = data.windows_bd.some((w) => byKey.has(`${e.name}:${w}`));
              if (!any) return null;
              return (
                <tr key={e.name}>
                  <th scope="row">
                    {e.label}
                    {e.name === data.official_close_to_close && <span className={styles.official}>oficial</span>}
                  </th>
                  {data.windows_bd.map((w) => (
                    <td key={w} className={styles.num}>
                      <EstimatedValueView value={byKey.get(`${e.name}:${w}`)?.latest} />
                    </td>
                  ))}
                  <td className={`${styles.muted} ${styles.small}`}>{e.hypothesis}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className={styles.controls} style={{ marginTop: 16 }}>
        <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          Janela
          <select className={styles.select} value={windowBd} onChange={(e) => setWindowBd(Number(e.target.value))}>
            {data.windows_bd.map((w) => (
              <option key={w} value={w}>
                {formatBusinessDays(w)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <RealizedChart data={data} windowBd={windowBd} />
    </>
  );
}

function RealizedChart({ data, windowBd }: { data: RealizedVolResponse; windowBd: number }) {
  const traces = useMemo<Data[]>(
    () =>
      data.estimators
        .filter((e) => e.window_bd === windowBd)
        .map((e, i) => ({
          type: 'scatter',
          mode: 'lines',
          name: ESTIMATOR_LABEL[e.estimator as EstimatorName],
          x: e.points.map((p) => p.as_of),
          // Sem número = lacuna (null): a linha quebra, nunca é interpolada (PRD-UI-05).
          y: e.points.map((p) => (p.status === 'ok' ? p.vol : null)),
          connectgaps: false,
          line: { width: e.estimator === data.official_close_to_close ? 2.5 : 1.5, color: CHART_COLORS.series[i % 7] },
          hovertemplate: '%{y}<extra>%{fullData.name}</extra>',
        })),
    [data, windowBd],
  );
  const layout = useMemo(
    () => ({
      xaxis: { type: 'date' as const, tickformat: CHART_DATE_TICKFORMAT, hoverformat: CHART_DATE_HOVERFORMAT },
      yaxis: { tickformat: CHART_VOL_TICKFORMAT, hoverformat: CHART_VOL_HOVERFORMAT, rangemode: 'tozero' as const },
    }),
    [],
  );
  return (
    <Plot
      data={traces}
      layout={layout}
      height={340}
      ariaLabel={`Volatilidade realizada por estimador, janela de ${formatBusinessDays(windowBd)}`}
    />
  );
}
