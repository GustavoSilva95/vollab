'use client';

import Link from 'next/link';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { ExposureOut, LimitsResponse, ScenarioOut } from '@vollab/api-types';
import { getLimitsOptions, getPortfolioOptions, postStressMutation } from '@vollab/api-types/react-query';
import {
  formatDate,
  formatMoney,
  formatNumber,
  formatRelative,
  formatReturn,
  formatVolShock,
  parsePercentInput,
  parseVolPointsInput,
} from '@/lib/format';
import { CRISIS_HELP, LIMIT_LABEL, LIMIT_STATE_LABEL, SCENARIO_ORIGIN_LABEL } from '@/lib/journal/labels';
import { NOT_CALIBRATED_HELP } from '@/lib/edge/labels';
import { problemMessage } from '@/lib/api/problem';
import styles from '../vol/vol.module.css';

/**
 * Carteira e risco (PRD 1.10 §8.1; RF-RSK-01..04, QA-12): Greeks e exposição a partir da última
 * marcação D-1 de cada operação aberta, stresses padrão e de crise, cenário avulso e limites.
 */
export default function PortfolioView() {
  const portfolio = useQuery(getPortfolioOptions());
  const limits = useQuery(getLimitsOptions());
  if (portfolio.isError || limits.isError) {
    return <p className={styles.error}>Não foi possível ler a carteira. O engine está no ar?</p>;
  }
  if (portfolio.isPending || limits.isPending) return <p className={styles.muted}>Calculando…</p>;
  const p = portfolio.data;
  const warnings = [...new Set([...p.warnings, ...limits.data.warnings])];
  return (
    <div className={styles.grid}>
      <section className={`${styles.card} ${styles.wide}`} aria-labelledby="pf-greeks">
        <h2 id="pf-greeks" className={`${styles.eyebrow} mono`}>
          Greeks da carteira · {formatNumber(p.positions_open)} operação(ões) aberta(s)
        </h2>
        <p className={styles.muted}>
          Marcação D-1:{' '}
          {Object.entries(p.mark_dates)
            .map(([t, d]) => `${t} em ${formatDate(d)}`)
            .join('; ') || 'nenhuma'}
          . Operações no <Link href="/app/diario">diário</Link>.
        </p>
        {warnings.map((w) => (
          <p key={w} className={styles.warn}>
            {w}
          </p>
        ))}
        {p.total == null ? (
          <p className={styles.muted}>Carteira vazia.</p>
        ) : (
          <ExposureTable rows={[{ ...p.total, ticker: 'Carteira' }, ...p.by_ticker]} first="Ativo" testId="pf-greeks" />
        )}
      </section>
      {p.by_expiry.length > 0 && (
        <section className={`${styles.card} ${styles.wide}`} aria-labelledby="pf-expiry">
          <h2 id="pf-expiry" className={`${styles.eyebrow} mono`}>
            Exposição por vencimento
          </h2>
          <ExposureTable rows={p.by_expiry} first="Ativo · vencimento" />
        </section>
      )}
      <Stress limits={limits.data} />
      <Limits limits={limits.data} />
    </div>
  );
}

function ExposureTable({ rows, first, testId }: { rows: ExposureOut[]; first: string; testId?: string }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} data-testid={testId}>
        <thead>
          <tr>
            <th scope="col">{first}</th>
            <th scope="col" className={styles.num}>
              Delta (ações)
            </th>
            <th scope="col" className={styles.num}>
              Delta (R$)
            </th>
            <th scope="col" className={styles.num}>
              Gamma (P&amp;L de 1%)
            </th>
            <th scope="col" className={styles.num}>
              Vega por ponto
            </th>
            <th scope="col" className={styles.num}>
              Theta por du
            </th>
            <th scope="col" className={styles.num}>
              Valor de mercado
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.ticker ?? ''}-${r.expiry ?? ''}`}>
              <td>
                {r.ticker}
                {r.expiry ? ` · ${formatDate(r.expiry)}` : ''}
              </td>
              <td className={styles.num}>{formatNumber(r.delta_shares, 1)}</td>
              <td className={styles.num}>{formatMoney(r.delta_brl)}</td>
              <td className={styles.num}>{formatMoney(r.gamma_1pct_brl)}</td>
              <td className={styles.num}>{formatMoney(r.vega_per_point_brl)}</td>
              <td className={styles.num}>{formatMoney(r.theta_per_bd_brl)}</td>
              <td className={styles.num}>{formatMoney(r.market_value_brl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function shocksText(sc: ScenarioOut): string {
  const [first] = sc.shocks;
  if (first == null) return 'sem choque medido';
  const same = sc.shocks.every((x) => x.spot_shock === first.spot_shock && x.vol_shock === first.vol_shock);
  const one = (x: ScenarioOut['shocks'][number]) => `${formatReturn(x.spot_shock, 1)} e ${formatVolShock(x.vol_shock)}`;
  if (same) return one(first);
  return sc.shocks.map((x) => `${x.ticker}: ${one(x)}`).join('; ');
}

const stressSchema = z.object({
  spot: z.string().refine((v) => {
    const x = parsePercentInput(v);
    return x != null && x >= -0.9 && x <= 0.9;
  }, 'Entre -90 e 90 (%).'),
  vol: z.string().refine((v) => {
    const x = parseVolPointsInput(v);
    return x != null && x >= -0.5 && x <= 2;
  }, 'Entre -50 e 200 pontos.'),
});

function Stress({ limits }: { limits: LimitsResponse }) {
  const form = useForm<z.infer<typeof stressSchema>>({
    resolver: zodResolver(stressSchema),
    defaultValues: { spot: '-15', vol: '20' },
  });
  const run = useMutation(postStressMutation());
  const onSubmit = form.handleSubmit((v) =>
    run.mutate({ body: { spot_shock: parsePercentInput(v.spot) as number, vol_shock: parseVolPointsInput(v.vol) as number } }),
  );
  const rows = run.data ? [...limits.scenarios, run.data] : limits.scenarios;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="pf-stress">
      <h2 id="pf-stress" className={`${styles.eyebrow} mono`}>
        Stress (reprecificação instantânea)
      </h2>
      <p className={`${styles.muted} ${styles.small}`}>
        Cada perna reprecificada por Black-Scholes com o choque, sem passar o tempo, com o hedge atual e sem custos de saída.
        IV nunca abaixo de 1%. <span title={CRISIS_HELP}>Cenários de crise: QA-12.</span>
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table} data-testid="pf-stress">
          <thead>
            <tr>
              <th scope="col">Cenário</th>
              <th scope="col">Choque</th>
              <th scope="col" className={styles.num}>
                P&amp;L
              </th>
              <th scope="col">Por ativo</th>
              <th scope="col">Origem</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((sc) => (
              <tr key={sc.name} data-testid={`stress-${sc.name}`}>
                <td>{sc.label}</td>
                <td className={styles.small}>{shocksText(sc)}</td>
                <td className={styles.num}>{formatMoney(sc.pnl_brl)}</td>
                <td className={styles.small}>
                  {sc.by_ticker.map((t) => `${t.ticker} ${formatMoney(t.pnl_brl)}`).join('; ')}
                  {sc.missing_tickers.length > 0 && (
                    <span className={styles.tag} title="Sem choque medido ou manual para estes ativos.">
                      sem choque: {sc.missing_tickers.join(', ')}
                    </span>
                  )}
                </td>
                <td>
                  {sc.origin !== 'estimated' && <span className={styles.tag}>{SCENARIO_ORIGIN_LABEL[sc.origin]}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className={styles.form} onSubmit={onSubmit} noValidate aria-label="Cenário avulso">
        <label className={styles.field}>
          <span>Choque no ativo (%)</span>
          <input className={styles.input} inputMode="decimal" {...form.register('spot')} />
          {form.formState.errors.spot && <span className={styles.fieldError}>{form.formState.errors.spot.message}</span>}
        </label>
        <label className={styles.field}>
          <span>Choque de vol (pontos)</span>
          <input className={styles.input} inputMode="decimal" {...form.register('vol')} />
          {form.formState.errors.vol && <span className={styles.fieldError}>{form.formState.errors.vol.message}</span>}
        </label>
        <div>
          <button type="submit" className={styles.button} disabled={run.isPending}>
            Rodar cenário avulso
          </button>
        </div>
      </form>
      {run.isError && <p className={styles.error}>{problemMessage(run.error, 'Não foi possível calcular.')}</p>}
    </section>
  );
}

export function Limits({ limits }: { limits: LimitsResponse }) {
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="pf-limits">
      <h2 id="pf-limits" className={`${styles.eyebrow} mono`}>
        Limites {limits.capital_brl ? `· capital ${formatMoney(limits.capital_brl)}` : ''}
      </h2>
      {limits.capital_brl == null && (
        <p className={styles.warn}>
          Sem capital informado os limites ficam indisponíveis: preencha em <Link href="/app/configuracoes">configurações</Link>.
        </p>
      )}
      <div className={styles.tableWrap}>
        <table className={styles.table} data-testid="pf-limits">
          <thead>
            <tr>
              <th scope="col">Limite</th>
              <th scope="col" className={styles.num}>
                Valor
              </th>
              <th scope="col" className={styles.num}>
                Limite
              </th>
              <th scope="col" className={styles.num}>
                Uso
              </th>
              <th scope="col">Estado</th>
            </tr>
          </thead>
          <tbody>
            {limits.limits.map((x) => (
              <tr key={`${x.name}-${x.scope ?? ''}`} data-state={x.state}>
                <td>
                  {LIMIT_LABEL[x.name]}
                  {x.scope ? ` · ${x.scope}` : ''}
                  {!x.calibrated && (
                    <span className={styles.tag} title={NOT_CALIBRATED_HELP}>
                      não calibrado
                    </span>
                  )}
                </td>
                <td className={styles.num}>{formatRelative(x.value)}</td>
                <td className={styles.num}>{formatRelative(x.limit)}</td>
                <td className={styles.num}>{formatRelative(x.usage)}</td>
                <td>
                  {x.state === 'breached' ? <strong className={styles.warn}>{LIMIT_STATE_LABEL.breached}</strong> : LIMIT_STATE_LABEL[x.state]}
                  {x.reason ? ` (${x.reason})` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
