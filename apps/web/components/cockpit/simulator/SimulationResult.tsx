'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import type { Data, Layout } from 'plotly.js';
import type { LimitsResponse, SimulationResponse, SizingOut } from '@vollab/api-types';
import Plot from '@/lib/charts/Plot';
import { CHART_COLORS } from '@/lib/charts/theme';
import {
  CHART_MONEY_HOVERFORMAT,
  CHART_MONEY_TICKFORMAT,
  CHART_MONEY_TICKPREFIX,
  formatBusinessDays,
  formatDate,
  formatDateTime,
  formatFraction,
  formatMoney,
  formatNumber,
  formatRate,
  formatRelative,
  formatSmallRate,
  formatVolPoints,
  formatVolShock,
} from '@/lib/format';
import { DIRECTION_LABEL, NOT_CALIBRATED_HELP, SPREAD_ESTIMATE_HELP } from '@/lib/edge/labels';
import { MODEL_LABEL } from '@/lib/forecast/labels';
import {
  DELTA_BAND_HELP,
  DISTRIBUTION_HELP,
  IV_CONSTANT_HELP,
  KAMAL_DERMAN_HELP,
  RULE_LABEL,
  stressLabel,
  STRUCTURE_LABEL,
} from '@/lib/simulator/labels';
import { LIMIT_LABEL, LIMIT_STATE_LABEL } from '@/lib/journal/labels';
import StateBadge from '../edge/StateBadge';
import EstimatedValueView from '../vol/EstimatedValueView';
import styles from '../vol/vol.module.css';
import local from './simulator.module.css';

const MANUAL_HELP = 'Valor informado pelo usuário (RF-SIM-03): IV, Greeks e edge recalculados com ele.';

function Tag({ children, help }: { children: string; help: string }) {
  return (
    <span className={styles.tag} title={help}>
      {children}
    </span>
  );
}

/**
 * Resultado da simulação e do dimensionamento (PRD 1.9 §5.8, §8.1). O semáforo e o número de edge
 * da estrutura ficam no topo (PRD-UI-01); estimativas e valores manuais são sempre rotulados (PRD-UI-02).
 */
export default function SimulationResult({
  sim,
  sizing,
  limits = null,
}: {
  sim: SimulationResponse;
  sizing: SizingOut;
  limits?: LimitsResponse | null;
}) {
  return (
    <div className={styles.grid}>
      <EdgeCard sim={sim} />
      <SizingCard sim={sim} sizing={sizing} />
      {limits && <ProformaLimits limits={limits} />}
      <LegsCard sim={sim} />
      <DistributionCard sim={sim} />
      <PayoffCard sim={sim} />
    </div>
  );
}

function EdgeCard({ sim }: { sim: SimulationResponse }) {
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-edge" data-testid="sim-edge">
      <h2 id="sim-edge" className={`${styles.eyebrow} mono`}>
        {STRUCTURE_LABEL[sim.structure]} · {sim.ticker} · vencimento {formatDate(sim.expiry)} (
        {formatBusinessDays(sim.horizon_bd)})
      </h2>
      <div className={styles.row}>
        <StateBadge row={{ state: sim.state, direction: sim.signal_direction ?? null, reason: sim.reason }} />
        <span>
          Estrutura de <strong>{DIRECTION_LABEL[sim.direction]}</strong>
          {sim.state === 'edge' && !sim.direction_match && (
            <span className={styles.warn}> · direção oposta à do sinal: o Kelly é zero (RN-SIZ-05)</span>
          )}
        </span>
      </div>
      {sim.reason && <p className={sim.state === 'unavailable' ? styles.warn : styles.muted}>{sim.reason}</p>}
      <dl className={styles.facts}>
        <dt>Prêmio de vol [intervalo]</dt>
        <dd>
          <EstimatedValueView value={sim.premium} format={formatVolPoints} showInterval />
        </dd>
        <dt>Edge relativo [intervalo]</dt>
        <dd>
          <EstimatedValueView value={sim.relative_edge} format={formatRelative} showInterval />
        </dd>
        <dt>Edge relativo líquido (direção da estrutura)</dt>
        <dd>{formatRelative(sim.net_relative_edge)}</dd>
        <dt>IV da estrutura (ex-evento)</dt>
        <dd>
          <EstimatedValueView value={sim.iv} />
        </dd>
        <dt>RV prevista [intervalo] · {MODEL_LABEL[sim.model as keyof typeof MODEL_LABEL] ?? sim.model}</dt>
        <dd>
          <EstimatedValueView value={sim.forecast} showInterval />
        </dd>
        <dt>Spread normal</dt>
        <dd>
          <EstimatedValueView value={sim.normal_spread} format={formatRelative} />
          {sim.normal_spread.calibrated === false && <Tag help={NOT_CALIBRATED_HELP}>não calibrado</Tag>}
        </dd>
        <dt>Custos + limiar (venda / compra)</dt>
        <dd>
          {sim.required_sell == null ? '—' : formatVolPoints(sim.required_sell)} /{' '}
          {sim.required_buy == null ? (sim.required_sell == null ? '—' : 'inviável') : formatVolPoints(sim.required_buy)}
          {sim.threshold.calibrated === false && <Tag help={NOT_CALIBRATED_HELP}>limiar não calibrado</Tag>}
        </dd>
        <dt>Ativo-objeto</dt>
        <dd>
          {formatMoney(sim.spot_brl)}
          {sim.spot_origin === 'manual' && <Tag help={MANUAL_HELP}>manual</Tag>}
          {sim.spot_at && <span className={styles.muted}> ({formatDateTime(sim.spot_at)})</span>}
          <span className={styles.muted}> · Selic {formatRate(sim.rate)}</span>
        </dd>
        <dt>Referência</dt>
        <dd>
          pregão {formatDate(sim.as_of)} · configuração v{sim.config_version_id} · intervalo de{' '}
          {formatFraction(sim.ci_level, 0)}
        </dd>
      </dl>
    </section>
  );
}

function SizingCard({ sim, sizing }: { sim: SimulationResponse; sizing: SizingOut }) {
  const zero = sizing.n_final === 0;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-size" data-testid="sim-sizing">
      <h2 id="sim-size" className={`${styles.eyebrow} mono`}>
        Dimensionamento
      </h2>
      {sizing.status === 'unavailable' ? (
        <p className={styles.warn}>{sizing.reason}</p>
      ) : (
        <>
          <p className={styles.headline}>
            <span data-testid="sim-size-final">{formatNumber(sizing.n_final)}</span> lote(s) de{' '}
            {formatNumber(sim.lot_size)} · <span data-testid="sim-size-rule">{RULE_LABEL[sizing.rule]}</span>
          </p>
          {zero && sizing.reason && <p className={styles.warn}>Tamanho zero: {sizing.reason}.</p>}
          <dl className={styles.facts}>
            <dt>Kelly fracionado ({formatFraction(sizing.kelly_fraction, 0)} do Kelly)</dt>
            <dd>
              {formatNumber(sizing.n_kelly)} lote(s)
              {sizing.kelly_full_lots != null && (
                <span className={styles.muted}> (Kelly cheio {formatNumber(sizing.kelly_full_lots, 1)})</span>
              )}
            </dd>
            <dt>Teto ({formatFraction(sizing.max_loss_fraction, 0)} do capital)</dt>
            <dd>{sizing.n_cap == null ? 'sem perda nos cenários' : `${formatNumber(sizing.n_cap)} lote(s)`}</dd>
            <dt>Capital</dt>
            <dd>{formatMoney(sizing.capital_brl)}</dd>
            <dt>P&amp;L esperado por lote no limite inferior do edge (μ)</dt>
            <dd>{formatMoney(sizing.mu_brl)}</dd>
            <dt>Perda máxima por lote (maior entre ES e stress)</dt>
            <dd>{formatMoney(sizing.max_loss_brl)}</dd>
            <dt>Margem (manual)</dt>
            <dd>
              {sizing.margin_per_lot_brl ? (
                <>
                  {formatMoney(sizing.margin_per_lot_brl)} por lote · total {formatMoney(sizing.margin_total_brl)} (
                  {formatFraction(sizing.margin_share_of_capital, 1)} do capital)
                  <Tag help="Margem informada pelo usuário (RN-SIZ-06); a plataforma não estima margem.">manual</Tag>
                </>
              ) : (
                <span className={styles.muted}>não informada</span>
              )}
            </dd>
          </dl>
        </>
      )}
      <h3 className={`${styles.eyebrow} mono`}>Stress na entrada (por lote, com o hedge inicial)</h3>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Cenário</th>
              <th scope="col" className={styles.num}>
                Ativo
              </th>
              <th scope="col" className={styles.num}>
                Vol
              </th>
              <th scope="col" className={styles.num}>
                Perda (− = ganho)
              </th>
            </tr>
          </thead>
          <tbody>
            {sizing.stress.map((s) => (
              <tr key={s.name}>
                <td>{stressLabel(s.name)}</td>
                <td className={styles.num}>{formatRelative(s.spot_shock, 1)}</td>
                <td className={styles.num}>{s.vol_shock ? formatVolShock(s.vol_shock, 1) : '—'}</td>
                <td className={styles.num}>{formatMoney(s.loss_brl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(sizing.stress_notes ?? []).map((n) => (
        <p key={n} className={`${styles.muted} ${styles.small}`}>
          {n} (o teto fica sem este cenário).
        </p>
      ))}
    </section>
  );
}

function ProformaLimits({ limits }: { limits: LimitsResponse }) {
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-limits" data-testid="sim-limits">
      <h2 id="sim-limits" className={`${styles.eyebrow} mono`}>
        Limites da carteira com a nova posição (pró-forma)
      </h2>
      {limits.capital_brl == null ? (
        <p className={styles.muted}>
          Informe o capital na <Link href="/app/configuracoes">configuração</Link> para avaliar os limites (RF-RSK-04); o
          capital digitado aqui vale só para o dimensionamento.
        </p>
      ) : (
        <ul className={styles.small}>
          {limits.limits.map((x) => (
            <li key={`${x.name}-${x.scope ?? ''}`} data-state={x.state}>
              {LIMIT_LABEL[x.name]}
              {x.scope ? ` · ${x.scope}` : ''}: {formatRelative(x.value)} de {formatRelative(x.limit)}{' '}
              {x.state === 'breached' ? (
                <strong className={styles.warn}>{LIMIT_STATE_LABEL.breached}</strong>
              ) : (
                LIMIT_STATE_LABEL[x.state]
              )}
              <Tag help={NOT_CALIBRATED_HELP}>não calibrado</Tag>
            </li>
          ))}
        </ul>
      )}
      {limits.breached && (
        <p className={styles.warn}>Com a nova posição algum limite é ultrapassado: o registro exige justificativa (PR-04).</p>
      )}
      {limits.warnings.map((w) => (
        <p key={w} className={`${styles.muted} ${styles.small}`}>
          {w}
        </p>
      ))}
    </section>
  );
}

function LegsCard({ sim }: { sim: SimulationResponse }) {
  const c = sim.costs;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-legs">
      <h2 id="sim-legs" className={`${styles.eyebrow} mono`}>
        Pernas, Greeks e custos
      </h2>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Série</th>
              <th scope="col" className={styles.num}>
                Qtd. por lote
              </th>
              <th scope="col" className={styles.num}>
                Strike (efetivo)
              </th>
              <th scope="col" className={styles.num}>
                K/F
              </th>
              <th scope="col" className={styles.num}>
                Preço
              </th>
              <th scope="col" className={styles.num}>
                IV
              </th>
              <th scope="col" className={styles.num}>
                Delta
              </th>
              <th scope="col" className={styles.num}>
                Vega/ponto
              </th>
              <th scope="col" className={styles.num}>
                Spread (faixa)
              </th>
            </tr>
          </thead>
          <tbody>
            {sim.legs.map((leg) => (
              <tr key={leg.series_id}>
                <td>
                  {leg.code} <span className={styles.muted}>({leg.option_type})</span>
                </td>
                <td className={styles.num}>{formatNumber(leg.quantity_per_lot)}</td>
                <td className={styles.num}>
                  {formatMoney(leg.strike)} ({formatMoney(leg.effective_strike)})
                </td>
                <td className={styles.num}>{formatNumber(leg.k_over_f, 3)}</td>
                <td className={styles.num}>
                  {formatMoney(leg.price_brl)}
                  {leg.price_origin === 'manual' ? (
                    <Tag help={MANUAL_HELP}>manual</Tag>
                  ) : (
                    <Tag help="Preço Black-Scholes com a IV de referência do pregão (RN-VOL-06).">estimado</Tag>
                  )}
                </td>
                <td className={styles.num}>
                  <EstimatedValueView value={leg.iv} />
                </td>
                <td className={styles.num}>{formatNumber(leg.delta, 3)}</td>
                <td className={styles.num}>{formatMoney(leg.vega_per_point, 4)}</td>
                <td className={styles.num}>
                  {leg.spread_conservative == null ? 'sem estimativa' : formatSmallRate(leg.spread_conservative)}{' '}
                  <span className={styles.muted}>({leg.band})</span>
                </td>
              </tr>
            ))}
            {sim.stock && (
              <tr>
                <td>
                  {sim.ticker} <span className={styles.muted}>(ação)</span>
                </td>
                <td className={styles.num}>{formatNumber(sim.stock.quantity_per_lot)}</td>
                <td colSpan={2} />
                <td className={styles.num}>{formatMoney(sim.stock.price_brl)}</td>
                <td colSpan={4} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <dl className={styles.facts}>
        <dt>Greeks por lote</dt>
        <dd>
          Δ {formatNumber(sim.greeks_lot.delta_shares, 1)} ações · Γ {formatNumber(sim.greeks_lot.gamma, 3)} · vega{' '}
          {formatMoney(sim.greeks_lot.vega_per_point_brl)}/ponto · theta {formatMoney(sim.greeks_lot.theta_per_bd_brl)}/du
        </dd>
        <dt>Greeks da posição ({formatNumber(sim.lots)} lote(s))</dt>
        <dd>
          Δ {formatNumber(sim.greeks_position.delta_shares, 1)} ações · vega{' '}
          {formatMoney(sim.greeks_position.vega_per_point_brl)}/ponto · theta{' '}
          {formatMoney(sim.greeks_position.theta_per_bd_brl)}/du
        </dd>
        <dt>Hedge</dt>
        <dd>
          {sim.dynamic_hedge ? (
            <>
              banda de delta <Tag help={DELTA_BAND_HELP}>não calibrada</Tag>
            </>
          ) : (
            'sem hedge dinâmico: a ação é a cobertura fixa'
          )}
        </dd>
      </dl>
      {c ? (
        <>
          <h3 className={`${styles.eyebrow} mono`}>
            Custos por lote (ida e volta) <Tag help={SPREAD_ESTIMATE_HELP}>estimativa</Tag>
          </h3>
          <dl className={styles.facts}>
            <dt>Opções</dt>
            <dd>
              spread {formatMoney(c.options_spread_brl)} + taxas {formatMoney(c.options_fees_brl)} + corretagem{' '}
              {formatMoney(c.options_brokerage_brl)}
              {c.stock_brl !== '0.00' && <> + ação {formatMoney(c.stock_brl)}</>} = {formatVolPoints(c.options_vol_pts, 2)}
            </dd>
            <dt>Hedge no semáforo (Leland, a cada {formatBusinessDays(c.hedge_interval_bd)})</dt>
            <dd>
              venda {formatVolPoints(c.hedge_sell_vol_pts, 2)} · compra{' '}
              {c.hedge_buy_vol_pts == null ? 'inviável' : formatVolPoints(c.hedge_buy_vol_pts, 2)}
            </dd>
            <dt>Hedge pela banda (média simulada)</dt>
            <dd>{formatMoney(c.band_hedge_cost_brl)}</dd>
            <dt>Total (venda / compra)</dt>
            <dd>
              {formatVolPoints(c.total_sell_vol_pts, 2)} /{' '}
              {c.total_buy_vol_pts == null ? 'inviável' : formatVolPoints(c.total_buy_vol_pts, 2)}
            </dd>
          </dl>
        </>
      ) : (
        <p className={styles.muted}>Custos indisponíveis.</p>
      )}
    </section>
  );
}

function DistributionCard({ sim }: { sim: SimulationResponse }) {
  const d = sim.distribution;
  const chart = useMemo(() => {
    if (d.status !== 'ok' || d.hist_counts.length === 0) return null;
    const mids = d.hist_counts.map((_, i) => ((d.hist_edges_brl[i] ?? 0) + (d.hist_edges_brl[i + 1] ?? 0)) / 2);
    const colors = mids.map((m) => (m < 0 ? CHART_COLORS.danger : CHART_COLORS.accent));
    const data: Data[] = [
      {
        type: 'bar',
        x: mids,
        y: d.hist_counts,
        marker: { color: colors },
        name: 'caminhos',
        hovertemplate: '%{x:' + CHART_MONEY_HOVERFORMAT + '}: %{y} caminhos<extra></extra>',
      },
    ];
    const layout: Partial<Layout> = {
      bargap: 0.02,
      hovermode: 'closest',
      showlegend: false,
      xaxis: { tickprefix: CHART_MONEY_TICKPREFIX, tickformat: CHART_MONEY_TICKFORMAT, title: { text: 'P&L por lote' } },
      yaxis: { title: { text: 'caminhos' } },
    };
    return { data, layout };
  }, [d]);
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-dist" data-testid="sim-distribution">
      <h2 id="sim-dist" className={`${styles.eyebrow} mono`}>
        Distribuição simulada do P&amp;L <Tag help={DISTRIBUTION_HELP}>estimativa</Tag>
        <Tag help={IV_CONSTANT_HELP}>IV constante</Tag>
      </h2>
      {d.status !== 'ok' ? (
        <p className={styles.warn}>
          {d.status === 'insufficient_data' ? 'Dados insuficientes' : 'Indisponível'}: {d.reason}
        </p>
      ) : (
        <>
          <dl className={styles.facts}>
            <dt>P&amp;L esperado líquido por lote (média)</dt>
            <dd className={local.big}>{formatMoney(d.mean_brl)}</dd>
            <dt>Desvio-padrão</dt>
            <dd>
              {formatMoney(d.std_brl)}
              {d.kamal_derman_std_brl && (
                <span className={styles.muted} title={KAMAL_DERMAN_HELP}>
                  {' '}
                  (eq. 7.7: {formatMoney(d.kamal_derman_std_brl)}, aproximado)
                </span>
              )}
            </dd>
            <dt>ES {formatFraction(d.es_level, 0)} (perda média no pior 1%)</dt>
            <dd>{formatMoney(d.es_brl)}</dd>
            <dt>Probabilidade de perda</dt>
            <dd>{formatFraction(d.prob_loss, 1)}</dd>
            <dt>Ajustes de hedge (média) e custo</dt>
            <dd>
              {formatNumber(d.mean_rehedges, 1)} · {formatMoney(d.mean_band_hedge_cost_brl)}
            </dd>
            <dt>Aproximado (vega × pontos líquidos)</dt>
            <dd>{formatMoney(sim.expected_pnl_approx_brl)}</dd>
          </dl>
          <p className={`${styles.muted} ${styles.small}`}>
            {formatNumber(d.paths)} caminhos, semente {d.seed}, amostra de {formatNumber(d.sample_size)} retornos (
            {formatDate(d.sample_start)} a {formatDate(d.sample_end)}). Percentis:{' '}
            {d.percentiles.map((p) => `p${p.percentile} ${formatMoney(p.pnl_brl)}`).join(' · ')}.
          </p>
          {chart && (
            <Plot data={chart.data} layout={chart.layout} height={280} ariaLabel="Histograma do P&L simulado por lote" />
          )}
        </>
      )}
    </section>
  );
}

function PayoffCard({ sim }: { sim: SimulationResponse }) {
  const chart = useMemo(() => {
    const data: Data[] = sim.payoff.curves.map((c, i) => ({
      type: 'scatter',
      mode: 'lines',
      x: sim.payoff.spots,
      y: c.pnl_brl,
      name: `${c.label} (${formatDate(c.day)})`,
      line: { color: CHART_COLORS.series[i % CHART_COLORS.series.length], width: c.label === 'vencimento' ? 2 : 1.5 },
      connectgaps: false,
    }));
    const spot = Number(sim.spot_brl);
    const layout: Partial<Layout> = {
      xaxis: { tickprefix: CHART_MONEY_TICKPREFIX, hoverformat: CHART_MONEY_HOVERFORMAT, title: { text: 'Ativo-objeto' } },
      yaxis: {
        tickprefix: CHART_MONEY_TICKPREFIX,
        tickformat: CHART_MONEY_TICKFORMAT,
        hoverformat: CHART_MONEY_HOVERFORMAT,
        title: { text: 'P&L por lote' },
      },
      shapes: [
        { type: 'line', xref: 'x', yref: 'paper', x0: spot, x1: spot, y0: 0, y1: 1, line: { color: CHART_COLORS.muted, dash: 'dot' } },
        { type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: CHART_COLORS.grid } },
      ],
    };
    return { data, layout };
  }, [sim]);
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-payoff">
      <h2 id="sim-payoff" className={`${styles.eyebrow} mono`}>
        Payoff (sem hedge nem custos)
      </h2>
      <Plot
        data={chart.data}
        layout={chart.layout}
        height={300}
        ariaLabel="Payoff por lote em função do preço do ativo, hoje, na metade da vida e no vencimento"
      />
    </section>
  );
}
