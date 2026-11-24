'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { ChainResponse, SizingRequest, SizingResponse } from '@vollab/api-types';
import { getChainOptions, listUnderlyingsOptions, postSizingMutation } from '@vollab/api-types/react-query';
import { formatBusinessDays, formatDate, formatMoney, formatNumber, formatVol, nowMarketInput } from '@/lib/format';
import { needsPut, simulatorSchema, toSizingRequest, type SimulatorValues } from '@/lib/simulator/form';
import { STRUCTURES, type StructureName } from '@/lib/simulator/labels';
import styles from '../vol/vol.module.css';
import EntryForm from './EntryForm';
import SimulationResult from './SimulationResult';

export function problemMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  return fallback;
}

/**
 * Simulador (PRD 1.9 §8.1; RF-SIM-01..05, RN-SIZ-01..06): monta a estrutura com séries reais,
 * aceita preços manuais, simula a distribuição do P&L, dimensiona e registra a entrada.
 * Nada é gravado antes de "Registrar entrada" (PRD §7).
 */
export default function SimulatorView({ initialTicker }: { initialTicker: string | null }) {
  const underlyings = useQuery(listUnderlyingsOptions());
  const tickers = (underlyings.data ?? []).filter((u) => u.active).map((u) => u.ticker);
  const [chosenTicker, setTicker] = useState<string | null>(initialTicker);
  const [expiry, setExpiry] = useState<string | null>(null);
  const ticker = chosenTicker ?? tickers[0] ?? null;

  const chain = useQuery({
    ...getChainOptions({ path: { ticker: ticker ?? '' }, query: expiry ? { expiry } : undefined }),
    enabled: ticker != null,
  });

  if (underlyings.isError) return <p className={styles.error}>Não foi possível ler os ativos. O engine está no ar?</p>;
  return (
    <div className={styles.grid}>
      <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-input">
        <h2 id="sim-input" className={`${styles.eyebrow} mono`}>
          Estrutura
        </h2>
        <div className={styles.controls}>
          <label>
            Ativo{' '}
            <select
              className={styles.select}
              value={ticker ?? ''}
              onChange={(e) => {
                setTicker(e.target.value);
                setExpiry(null);
              }}
            >
              {ticker && !tickers.includes(ticker) && <option value={ticker}>{ticker}</option>}
              {tickers.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          {chain.data && chain.data.expiries.length > 0 && (
            <label>
              Vencimento{' '}
              <select
                className={styles.select}
                value={chain.data.expiry ?? ''}
                onChange={(e) => setExpiry(e.target.value)}
              >
                {chain.data.expiries.map((x) => (
                  <option key={x} value={x}>
                    {formatDate(x)}
                    {chain.data.expiries_with_iv.includes(x) ? ' (com IV)' : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
          {ticker && (
            <Link className={styles.link} href={`/app/ativos/${ticker}`}>
              Ver {ticker}
            </Link>
          )}
        </div>
        {chain.isError && <p className={styles.error}>{problemMessage(chain.error, 'Não foi possível ler a cadeia.')}</p>}
        {chain.isPending && ticker && <p className={styles.muted}>Carregando séries…</p>}
        {chain.data && chain.data.series.length === 0 && (
          <p className={styles.muted}>Sem séries de opção no último pregão: rode a coleta.</p>
        )}
        {chain.data && ticker && chain.data.series.length > 0 && (
          <SimulatorForm key={`${ticker}-${chain.data.expiry}`} ticker={ticker} chain={chain.data} />
        )}
      </section>
    </div>
  );
}

function SimulatorForm({ ticker, chain }: { ticker: string; chain: ChainResponse }) {
  const first: StructureName = 'short_straddle';
  const suggest = (s: StructureName) => {
    const ids = chain.suggestions[s] ?? [];
    const byId = new Map(chain.series.map((x) => [x.series_id, x]));
    const call = ids.find((i) => byId.get(i)?.option_type === 'call');
    const put = ids.find((i) => byId.get(i)?.option_type === 'put');
    return { call: call != null ? String(call) : '', put: put != null ? String(put) : '' };
  };
  const form = useForm<SimulatorValues>({
    resolver: zodResolver(simulatorSchema),
    defaultValues: {
      structure: first,
      ...suggest(first),
      manualSpot: '',
      manualCall: '',
      manualPut: '',
      manualAt: nowMarketInput(),
      capital: '',
      marginPerLot: '',
      lots: '1',
    },
  });
  const structure = useWatch({ control: form.control, name: 'structure' });
  const [request, setRequest] = useState<SizingRequest | null>(null);
  const [result, setResult] = useState<SizingResponse | null>(null);
  const run = useMutation({
    ...postSizingMutation(),
    onSuccess: (data) => setResult(data),
  });
  const errors = form.formState.errors;
  const calls = chain.series.filter((s) => s.option_type === 'call');
  const puts = chain.series.filter((s) => s.option_type === 'put');
  const seriesLabel = (s: ChainResponse['series'][number]) =>
    `${s.code} · K ${formatMoney(s.effective_strike)} · K/F ${formatNumber(s.k_over_f, 3)}` +
    (s.iv != null ? ` · IV ${formatVol(s.iv, 1)}` : ' · sem IV');

  const onSubmit = form.handleSubmit((values) => {
    const body = toSizingRequest(ticker, values);
    setRequest(body);
    setResult(null);
    run.mutate({ body });
  });

  return (
    <>
      <p className={styles.muted}>
        Pregão {formatDate(chain.as_of)} · ativo {formatMoney(chain.spot_brl)} · vencimento {formatDate(chain.expiry)} (
        {formatBusinessDays(chain.days_to_expiry_bd)}). Séries sugeridas pela estrutura; troque à vontade.
      </p>
      <form className={styles.form} onSubmit={onSubmit} noValidate aria-label="Simular estrutura">
        <label className={styles.field}>
          <span>Estrutura</span>
          <select
            className={styles.select}
            {...form.register('structure', {
              onChange: (e) => {
                const s = suggest(e.target.value as StructureName);
                form.setValue('call', s.call);
                form.setValue('put', s.put);
              },
            })}
          >
            {STRUCTURES.map((s) => (
              <option key={s.name} value={s.name}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>Call</span>
          <select className={styles.select} {...form.register('call')}>
            <option value="">—</option>
            {calls.map((s) => (
              <option key={s.series_id} value={s.series_id}>
                {seriesLabel(s)}
              </option>
            ))}
          </select>
          {errors.call && <span className={styles.fieldError}>{errors.call.message}</span>}
        </label>
        {needsPut(structure) && (
          <label className={styles.field}>
            <span>Put</span>
            <select className={styles.select} {...form.register('put')}>
              <option value="">—</option>
              {puts.map((s) => (
                <option key={s.series_id} value={s.series_id}>
                  {seriesLabel(s)}
                </option>
              ))}
            </select>
            {errors.put && <span className={styles.fieldError}>{errors.put.message}</span>}
          </label>
        )}
        <fieldset className={styles.form}>
          <legend className={`${styles.eyebrow} mono`}>Preços do momento (opcional, manual)</legend>
          <label className={styles.field}>
            <span>Ativo-objeto (R$)</span>
            <input className={styles.input} inputMode="decimal" placeholder="último fechamento" {...form.register('manualSpot')} />
            {errors.manualSpot && <span className={styles.fieldError}>{errors.manualSpot.message}</span>}
          </label>
          <label className={styles.field}>
            <span>Call (R$)</span>
            <input className={styles.input} inputMode="decimal" placeholder="pela IV de referência" {...form.register('manualCall')} />
            {errors.manualCall && <span className={styles.fieldError}>{errors.manualCall.message}</span>}
          </label>
          {needsPut(structure) && (
            <label className={styles.field}>
              <span>Put (R$)</span>
              <input className={styles.input} inputMode="decimal" placeholder="pela IV de referência" {...form.register('manualPut')} />
              {errors.manualPut && <span className={styles.fieldError}>{errors.manualPut.message}</span>}
            </label>
          )}
          <label className={styles.field}>
            <span>Data e hora (Brasília)</span>
            <input className={styles.input} type="datetime-local" {...form.register('manualAt')} />
            {errors.manualAt && <span className={styles.fieldError}>{errors.manualAt.message}</span>}
          </label>
        </fieldset>
        <fieldset className={styles.form}>
          <legend className={`${styles.eyebrow} mono`}>Dimensionamento</legend>
          <label className={styles.field}>
            <span>Capital para opções (R$)</span>
            <input className={styles.input} inputMode="decimal" placeholder="o da configuração" {...form.register('capital')} />
            {errors.capital && <span className={styles.fieldError}>{errors.capital.message}</span>}
          </label>
          <label className={styles.field}>
            <span>Margem por lote (R$, manual)</span>
            <input className={styles.input} inputMode="decimal" placeholder="opcional" {...form.register('marginPerLot')} />
            {errors.marginPerLot && <span className={styles.fieldError}>{errors.marginPerLot.message}</span>}
          </label>
          <label className={styles.field}>
            <span>Lotes (Greeks da posição)</span>
            <input className={styles.input} inputMode="numeric" {...form.register('lots')} />
            {errors.lots && <span className={styles.fieldError}>{errors.lots.message}</span>}
          </label>
        </fieldset>
        <div>
          <button type="submit" className={styles.button} disabled={run.isPending}>
            {run.isPending ? 'Simulando…' : 'Simular e dimensionar'}
          </button>
        </div>
      </form>
      {run.isError && <p className={styles.error}>{problemMessage(run.error, 'Não foi possível simular.')}</p>}
      {result && request && (
        <div className={styles.grid} style={{ marginTop: 16 }}>
          <SimulationResult sim={result.simulation} sizing={result.sizing} />
          <EntryForm key={JSON.stringify(request)} request={request} result={result} />
        </div>
      )}
    </>
  );
}
