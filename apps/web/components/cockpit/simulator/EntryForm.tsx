'use client';

import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { PositionOut, SizingRequest, SizingResponse } from '@vollab/api-types';
import { postPositionMutation } from '@vollab/api-types/react-query';
import { formatDateTime, formatMoney, formatNumber, nowMarketInput, toMoneyInput } from '@/lib/format';
import { STATE_LABEL } from '@/lib/edge/labels';
import { MODEL_LABEL } from '@/lib/forecast/labels';
import { entrySchema, overrideReasons, toPositionCreate, type EntryValues } from '@/lib/simulator/form';
import { RULE_LABEL, STRUCTURE_LABEL } from '@/lib/simulator/labels';
import styles from '../vol/vol.module.css';
import { problemMessage } from './SimulatorView';

/**
 * Registro da entrada (RF-DIA-01, RN-EDG-06, CS-01): envia só os insumos e o executado; o engine
 * recalcula edge, semáforo, simulação e dimensionamento e grava o retrato imutável. Fora da regra
 * (semáforo, direção ou lotes acima do sugerido) a justificativa é obrigatória.
 */
export default function EntryForm({ request, result }: { request: SizingRequest; result: SizingResponse }) {
  const { simulation: sim, sizing } = result;
  const queryClient = useQueryClient();
  const form = useForm<EntryValues>({
    resolver: zodResolver(entrySchema),
    defaultValues: {
      lots: String(Math.max(sizing.n_final, 1)),
      prices: sim.legs.map((l) => toMoneyInput(l.price_brl)),
      fees: sim.legs.map(() => ''),
      stockPrice: sim.stock ? toMoneyInput(sim.stock.price_brl) : '',
      executedAt: nowMarketInput(),
      note: '',
      overrideReason: '',
    },
  });
  const lots = Number(useWatch({ control: form.control, name: 'lots' })) || 0;
  const reasons = overrideReasons(sim, sizing, lots);
  const save = useMutation({
    ...postPositionMutation(),
    onSuccess: () =>
      queryClient.invalidateQueries({
        predicate: (q) => ['listPositions'].includes((q.queryKey[0] as { _id?: string } | undefined)?._id ?? ''),
      }),
  });
  const errors = form.formState.errors;

  if (sim.state === 'unavailable') {
    return (
      <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-entry">
        <h2 id="sim-entry" className={`${styles.eyebrow} mono`}>
          Registrar entrada
        </h2>
        <p className={styles.warn}>
          Sem semáforo não existe entrada (CS-01): resolva o motivo acima antes de registrar.
        </p>
      </section>
    );
  }
  if (save.data) return <Registered position={save.data} />;

  const onSubmit = form.handleSubmit((values) => {
    if (reasons.length > 0 && values.overrideReason.trim().length < 10) {
      form.setError('overrideReason', { message: 'Justifique a entrada fora da regra (mín. 10 caracteres).' });
      return;
    }
    save.mutate({ body: toPositionCreate(request, sim, values) });
  });

  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-entry">
      <h2 id="sim-entry" className={`${styles.eyebrow} mono`}>
        Registrar entrada
      </h2>
      <p className={styles.muted}>
        Sugerido: {formatNumber(sizing.n_final)} lote(s). O engine recalcula tudo e grava o retrato da decisão com a
        configuração v{sim.config_version_id}.
      </p>
      <form className={styles.form} onSubmit={onSubmit} noValidate aria-label="Registrar entrada">
        <label className={styles.field}>
          <span>Lotes executados</span>
          <input className={styles.input} inputMode="numeric" {...form.register('lots')} />
          {errors.lots && <span className={styles.fieldError}>{errors.lots.message}</span>}
        </label>
        {sim.legs.map((leg, i) => (
          <div key={leg.series_id} className={styles.field}>
            <label htmlFor={`price-${leg.series_id}`}>Preço executado {leg.code} (R$)</label>
            <input
              id={`price-${leg.series_id}`}
              className={styles.input}
              inputMode="decimal"
              {...form.register(`prices.${i}` as const)}
            />
            <label htmlFor={`fees-${leg.series_id}`}>Taxas e corretagem {leg.code} (R$)</label>
            <input
              id={`fees-${leg.series_id}`}
              className={styles.input}
              inputMode="decimal"
              placeholder="0"
              {...form.register(`fees.${i}` as const)}
            />
            {errors.prices?.[i] && <span className={styles.fieldError}>{errors.prices[i]?.message}</span>}
          </div>
        ))}
        {sim.stock && (
          <label className={styles.field}>
            <span>
              Ação comprada: {formatNumber(sim.stock.quantity_per_lot * Math.max(lots, 0))} a (R$)
            </span>
            <input className={styles.input} inputMode="decimal" {...form.register('stockPrice')} />
          </label>
        )}
        <label className={styles.field}>
          <span>Executado em (Brasília)</span>
          <input className={styles.input} type="datetime-local" {...form.register('executedAt')} />
          {errors.executedAt && <span className={styles.fieldError}>{errors.executedAt.message}</span>}
        </label>
        <label className={styles.field}>
          <span>Nota</span>
          <input className={styles.input} placeholder="opcional" {...form.register('note')} />
        </label>
        {reasons.length > 0 && (
          <label className={styles.field} style={{ gridColumn: '1 / -1' }}>
            <span className={styles.warn}>Fora da regra: {reasons.join('; ')}. Justificativa obrigatória.</span>
            <input className={styles.input} {...form.register('overrideReason')} />
            {errors.overrideReason && <span className={styles.fieldError}>{errors.overrideReason.message}</span>}
          </label>
        )}
        <div>
          <button type="submit" className={styles.button} disabled={save.isPending}>
            {save.isPending ? 'Registrando…' : 'Registrar entrada'}
          </button>
        </div>
      </form>
      {save.isError && <p className={styles.error}>{problemMessage(save.error, 'Não foi possível registrar.')}</p>}
    </section>
  );
}

function Registered({ position }: { position: PositionOut }) {
  const snap = position.decision_snapshot as {
    simulation?: { state?: string; config_version_id?: number; engine_version?: string };
    sizing?: { rule?: keyof typeof RULE_LABEL; n_final?: number };
  };
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="sim-registered" data-testid="sim-registered">
      <h2 id="sim-registered" className={`${styles.eyebrow} mono`}>
        Entrada registrada · operação {position.id}
      </h2>
      <dl className={styles.facts}>
        <dt>Estrutura</dt>
        <dd>
          {STRUCTURE_LABEL[position.structure]} {position.ticker} · {formatNumber(position.lots)} lote(s)
        </dd>
        <dt>Semáforo na entrada</dt>
        <dd data-testid="snapshot-state">{STATE_LABEL[position.edge_state]}</dd>
        <dt>Modelo</dt>
        <dd data-testid="snapshot-model">{MODEL_LABEL[position.model as keyof typeof MODEL_LABEL] ?? position.model}</dd>
        <dt>Configuração</dt>
        <dd data-testid="snapshot-config">v{position.config_version_id}</dd>
        <dt>Dimensionamento</dt>
        <dd>
          {snap.sizing?.rule ? RULE_LABEL[snap.sizing.rule] : '—'} · sugerido {formatNumber(snap.sizing?.n_final)} lote(s)
        </dd>
        <dt>Override</dt>
        <dd>{position.override_reason ?? 'não'}</dd>
        <dt>Registrado em</dt>
        <dd>
          {formatDateTime(position.created_at)} · engine {snap.simulation?.engine_version ?? position.engine_version}
        </dd>
        <dt>Lançamentos</dt>
        <dd>
          {position.entries.map((e) => (
            <div key={e.id} className={styles.small}>
              {e.instrument}: {formatNumber(e.quantity)} a {formatMoney(e.price_brl)}
            </div>
          ))}
        </dd>
      </dl>
      <p className={`${styles.muted} ${styles.small}`}>
        O retrato é imutável. Lançamentos de hedge, marcação e atribuição chegam na Etapa 7 (Diário).
      </p>
    </section>
  );
}
