'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Data } from 'plotly.js';
import type {
  EvaluationPointsResponse,
  EvaluationResponse,
  ForecastOut,
  ForecastsResponse,
} from '@vollab/api-types';
import {
  getForecastsOptions,
  getModelsEvaluationOptions,
  getModelsEvaluationPointsOptions,
  listUnderlyingsOptions,
  putModelSelectionMutation,
} from '@vollab/api-types/react-query';
import Plot from '@/lib/charts/Plot';
import { CHART_COLORS } from '@/lib/charts/theme';
import {
  CHART_DATE_HOVERFORMAT,
  CHART_DATE_TICKFORMAT,
  CHART_VOL_HOVERFORMAT,
  CHART_VOL_TICKFORMAT,
  formatBusinessDays,
  formatDate,
  formatNumber,
  formatRatio,
  formatVol,
  formatVolPoints,
} from '@/lib/format';
import { FORECAST_MODELS, MODEL_HELP, MODEL_LABEL, type EvaluatedName } from '@/lib/forecast/labels';
import EstimatedValueView from '../vol/EstimatedValueView';
import styles from '../vol/vol.module.css';

type ModelName = ForecastsResponse['selected_model'];

/**
 * Tela de modelos (PRD 1.7 §8.1, RF-PRV-01..04, CS-03): previsão atual de cada modelo com intervalo,
 * erro de previsão contra os baselines em janelas não sobrepostas e a escolha do modelo do edge.
 */
export default function ModelsView() {
  const underlyings = useQuery(listUnderlyingsOptions());
  const active = useMemo(() => (underlyings.data ?? []).filter((u) => u.active), [underlyings.data]);
  const [chosen, setTicker] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<number | null>(null);
  // Sem escolha ainda: o primeiro ativo ativo (derivado, sem efeito).
  const ticker = chosen ?? active[0]?.ticker ?? null;

  if (underlyings.isError) return <p className={styles.error}>Não foi possível listar os ativos. O engine está no ar?</p>;
  if (underlyings.data && active.length === 0) return <p className={styles.muted}>Nenhum ativo ativo cadastrado.</p>;
  if (ticker == null) return <p className={styles.muted}>Carregando…</p>;

  return (
    <div className={styles.grid}>
      <div className={`${styles.controls} ${styles.wide}`}>
        <label>
          Ativo{' '}
          <select className={styles.select} value={ticker} onChange={(e) => setTicker(e.target.value)}>
            {active.map((u) => (
              <option key={u.ticker} value={u.ticker}>
                {u.ticker}
              </option>
            ))}
          </select>
        </label>
        <HorizonSelect ticker={ticker} value={horizon} onChange={setHorizon} />
      </div>
      <ForecastCard ticker={ticker} horizon={horizon} />
      <EvaluationCard ticker={ticker} horizon={horizon} />
      <EvaluationChartCard ticker={ticker} horizon={horizon} />
    </div>
  );
}

function query(ticker: string, horizon: number | null) {
  return { query: horizon == null ? { underlying: ticker } : { underlying: ticker, horizon_bd: horizon } };
}

function HorizonSelect({
  ticker,
  value,
  onChange,
}: {
  ticker: string;
  value: number | null;
  onChange: (h: number | null) => void;
}) {
  const { data } = useQuery(getModelsEvaluationOptions(query(ticker, null)));
  if (!data || data.evaluated_horizons_bd.length < 2) {
    return data ? (
      <span className={styles.muted}>Horizonte avaliado: {formatBusinessDays(data.horizon_bd)}</span>
    ) : null;
  }
  return (
    <label>
      Horizonte{' '}
      <select
        className={styles.select}
        value={value ?? data.horizon_bd}
        onChange={(e) => onChange(Number(e.target.value))}
      >
        {data.evaluated_horizons_bd.map((h) => (
          <option key={h} value={h}>
            {formatBusinessDays(h)}
          </option>
        ))}
      </select>
    </label>
  );
}

// --- Previsão atual -----------------------------------------------------------------------------

function ForecastCard({ ticker, horizon }: { ticker: string; horizon: number | null }) {
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery(getForecastsOptions(query(ticker, horizon)));
  const select = useMutation({
    ...putModelSelectionMutation(),
    // A escolha é global (todos os ativos e horizontes): uma invalidação por predicado basta.
    onSuccess: () => queryClient.invalidateQueries({ predicate: (q) => isForecastQuery(q.queryKey) }),
  });
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="fc-title" aria-busy={isPending}>
      <h2 id="fc-title" className={`${styles.eyebrow} mono`}>
        RV prevista
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar a previsão.</p>}
      {data && data.items.length === 0 && (
        <p className={styles.muted}>Sem previsão calculada ainda: rode a coleta; o worker calcula em seguida.</p>
      )}
      {data && data.items.length > 0 && (
        <>
          <ForecastTable
            data={data}
            pending={select.isPending}
            onSelect={(model) => select.mutate({ body: { model } })}
          />
          {select.isError && <p className={styles.error}>{problemDetail(select.error)}</p>}
        </>
      )}
    </section>
  );
}

function isForecastQuery(key: readonly unknown[]): boolean {
  const first = key[0] as { _id?: string } | undefined;
  // O ranking usa o modelo escolhido (RF-PRV-04): também é invalidado.
  return first?._id === 'getForecasts' || first?._id === 'getModelsEvaluation' || first?._id === 'getRanking';
}

function problemDetail(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  return 'Não foi possível trocar o modelo.';
}

export function ForecastTable({
  data,
  pending = false,
  onSelect,
}: {
  data: ForecastsResponse;
  pending?: boolean;
  onSelect?: (model: ModelName) => void;
}) {
  const selected = data.items.find((i) => i.selected);
  return (
    <>
      <p className={styles.muted}>
        Em {formatDate(data.as_of)}, horizonte de {formatBusinessDays(data.horizon_bd)}: vol anualizada média esperada até
        lá, só com dados até o pregão. Intervalo de {formatNumber(data.ci_level * 100)}%.{' '}
        <strong>Modelo em uso no edge: {MODEL_LABEL[data.selected_model]}</strong>
        {selected && !selected.eligible && (
          <span className={styles.warn}> — sem avaliação suficiente neste ativo: o edge fica indisponível.</span>
        )}
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Modelo</th>
              <th scope="col" className={styles.num}>
                Previsão [intervalo]
              </th>
              <th scope="col">Parâmetros</th>
              <th scope="col">Uso no edge</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.model}>
                <th scope="row" title={MODEL_HELP[item.model]}>
                  {MODEL_LABEL[item.model]}
                  {item.selected && <span className={styles.official}>em uso</span>}
                </th>
                <td className={styles.num}>
                  <EstimatedValueView value={item.forecast} showInterval />
                </td>
                <td className={styles.small}>
                  <StateSummary item={item} />
                </td>
                <td>
                  {item.kind === 'baseline' ? (
                    <span className={styles.muted}>baseline</span>
                  ) : item.selected ? (
                    <span>em uso</span>
                  ) : item.eligible ? (
                    <button
                      type="button"
                      className={styles.ghost}
                      disabled={pending || !onSelect}
                      onClick={() => onSelect?.(item.model as ModelName)}
                    >
                      Usar no edge
                    </button>
                  ) : (
                    <span className={styles.state} title={item.eligibility_reason ?? undefined}>
                      não elegível
                      {item.eligibility_reason && <span className="sr-only">: {item.eligibility_reason}</span>}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function StateSummary({ item }: { item: ForecastOut }) {
  const s = item.state;
  if (!s) return <span className={styles.muted}>—</span>;
  const parts: string[] = [];
  if (s.ewma_lambda != null) parts.push(`λ ${formatRatio(s.ewma_lambda)}`);
  if (s.persistence != null) parts.push(`α + β ${formatRatio(s.persistence, 3)}`);
  if (s.long_run_vol != null) parts.push(`vol de longo prazo ${formatVol(s.long_run_vol)}`);
  if (s.components) parts.push(`${formatNumber(s.components.length)} estimadores`);
  if (s.n_returns != null) parts.push(`${formatNumber(s.n_returns)} retornos`);
  return <span className={styles.muted}>{parts.join(' · ') || '—'}</span>;
}

// --- Avaliação ----------------------------------------------------------------------------------

function EvaluationCard({ ticker, horizon }: { ticker: string; horizon: number | null }) {
  const { data, isPending, isError } = useQuery(getModelsEvaluationOptions(query(ticker, horizon)));
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="ev-title" aria-busy={isPending}>
      <h2 id="ev-title" className={`${styles.eyebrow} mono`}>
        Erro de previsão × baselines
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar a avaliação.</p>}
      {data && data.rows.length === 0 && <p className={styles.muted}>Sem avaliação calculada ainda.</p>}
      {data && data.rows.length > 0 && <EvaluationTable data={data} />}
    </section>
  );
}

export function EvaluationTable({ data }: { data: EvaluationResponse }) {
  return (
    <>
      <p className={styles.muted}>
        Janelas não sobrepostas de {formatBusinessDays(data.horizon_bd)} (nenhum pregão em duas janelas), as mesmas
        para todos. Erro = previsão − RV close-to-close realizada na janela, em pontos de vol. Razão &lt; 1: o modelo
        erra menos que o baseline. Abaixo de {formatNumber(data.min_windows)} janelas: dados insuficientes. Com 1 ano
        de histórico há poucas janelas: leia os intervalos antes do número.
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Modelo</th>
              <th scope="col" className={styles.num}>
                Janelas
              </th>
              <th scope="col" className={styles.num}>
                Viés
              </th>
              <th scope="col" className={styles.num}>
                MAE
              </th>
              <th scope="col" className={styles.num}>
                RMSE [intervalo]
              </th>
              <th scope="col" className={styles.num}>
                ÷ RV C2C 20 du
              </th>
              <th scope="col" className={styles.num}>
                ÷ IV
              </th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => {
              const discarded = row.discarded_no_forecast + row.discarded_incomplete_realized;
              return (
                <tr key={row.model}>
                  <th scope="row" title={MODEL_HELP[row.model]}>
                    {MODEL_LABEL[row.model]}
                    {row.model === data.selected_model && <span className={styles.official}>em uso</span>}
                  </th>
                  <td
                    className={styles.num}
                    title={
                      discarded > 0
                        ? `${formatNumber(row.discarded_no_forecast)} sem previsão na origem; ${formatNumber(row.discarded_incomplete_realized)} com janela realizada incompleta`
                        : undefined
                    }
                  >
                    {formatNumber(row.n_windows)}
                    {discarded > 0 && <span className={styles.muted}> (+{formatNumber(discarded)} fora)</span>}
                  </td>
                  <td className={styles.num}>{formatVolPoints(row.bias)}</td>
                  <td className={styles.num}>{formatVolPoints(row.mae)}</td>
                  <td className={styles.num}>
                    <EstimatedValueView value={row.rmse} format={formatVolPoints} showInterval />
                  </td>
                  {(['rv_c2c_20', 'implied'] as const).map((b) => {
                    const ratio = row.ratios.find((r) => r.baseline === b);
                    return (
                      <td key={b} className={styles.num}>
                        {ratio ? (
                          <EstimatedValueView value={ratio.ratio} format={(v) => formatRatio(v)} showInterval />
                        ) : (
                          <span className={styles.muted}>—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {data.engine_version && (
        <p className={`${styles.muted} ${styles.small}`}>
          Calculado pelo engine {data.engine_version}, configuração {formatNumber(data.config_version_id)}.
        </p>
      )}
    </>
  );
}

// --- Previsto × realizado -----------------------------------------------------------------------

function EvaluationChartCard({ ticker, horizon }: { ticker: string; horizon: number | null }) {
  const { data, isPending, isError } = useQuery(getModelsEvaluationPointsOptions(query(ticker, horizon)));
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="pts-title" aria-busy={isPending}>
      <h2 id="pts-title" className={`${styles.eyebrow} mono`}>
        Previsto × realizado por janela
      </h2>
      {isError && <p className={styles.error}>Não foi possível carregar as janelas avaliadas.</p>}
      {data && data.series.length === 0 && <p className={styles.muted}>Sem janelas avaliadas ainda.</p>}
      {data && data.series.length > 0 && <EvaluationChart data={data} />}
    </section>
  );
}

const MODEL_COLORS: Record<EvaluatedName, string> = Object.fromEntries(
  FORECAST_MODELS.map((m, i) => [m.name, CHART_COLORS.series[i + 1] ?? CHART_COLORS.muted]),
) as Record<EvaluatedName, string>;

function EvaluationChart({ data }: { data: EvaluationPointsResponse }) {
  const models = data.series.map((s) => s.model);
  const [shown, setShown] = useState<EvaluatedName>(models.includes('ewma') ? 'ewma' : (models[0] ?? 'ewma'));
  const series = data.series.find((s) => s.model === shown);

  const traces = useMemo<Data[]>(() => {
    const realized = data.series[0]?.points ?? [];
    // Eixo x = fim da janela (quando a RV realizada fica conhecida). Lacunas quebram a linha.
    const out: Data[] = [
      {
        type: 'scatter',
        mode: 'lines+markers',
        name: 'RV realizada na janela',
        x: realized.map((p) => p.window_end),
        y: realized.map((p) => p.realized ?? null),
        connectgaps: false,
        line: { color: CHART_COLORS.fg },
      },
    ];
    if (series) {
      const x = series.points.map((p) => p.window_end);
      out.push(
        {
          type: 'scatter',
          mode: 'lines',
          name: 'Intervalo (limite inferior)',
          x,
          y: series.points.map((p) => p.forecast_ci_low ?? null),
          connectgaps: false,
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
        {
          type: 'scatter',
          mode: 'lines',
          name: series.ci_origin === 'estimated' ? 'Intervalo (erro avaliado)' : 'Intervalo aproximado (χ²)',
          x,
          y: series.points.map((p) => p.forecast_ci_high ?? null),
          connectgaps: false,
          fill: 'tonexty',
          fillcolor: 'rgba(127, 209, 199, 0.15)',
          line: { width: 0 },
        },
        {
          type: 'scatter',
          mode: 'lines+markers',
          name: `Previsão: ${MODEL_LABEL[series.model]}`,
          x,
          y: series.points.map((p) => p.forecast ?? null),
          connectgaps: false,
          line: { color: MODEL_COLORS[series.model], dash: 'dot' },
        },
      );
    }
    return out;
  }, [data, series]);

  return (
    <>
      <div className={styles.controls}>
        <label>
          Modelo{' '}
          <select className={styles.select} value={shown} onChange={(e) => setShown(e.target.value as EvaluatedName)}>
            {models.map((m) => (
              <option key={m} value={m}>
                {MODEL_LABEL[m]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className={`${styles.muted} ${styles.small}`}>
        Cada ponto é uma janela de {formatBusinessDays(data.horizon_bd)}, marcada no último pregão dela. Janelas sem
        previsão ou com realizada incompleta aparecem como quebra na linha.
      </p>
      <Plot
        data={traces}
        layout={{
          xaxis: { type: 'date', tickformat: CHART_DATE_TICKFORMAT, hoverformat: CHART_DATE_HOVERFORMAT },
          yaxis: { tickformat: CHART_VOL_TICKFORMAT, hoverformat: CHART_VOL_HOVERFORMAT, rangemode: 'tozero' },
        }}
        height={320}
        ariaLabel={`Previsão do modelo ${MODEL_LABEL[shown]} e RV realizada em cada janela não sobreposta`}
      />
    </>
  );
}
