'use client';

import Link from 'next/link';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AttributionOut, PositionOut } from '@vollab/api-types';
import { getPositionOptions, postEntryMutation } from '@vollab/api-types/react-query';
import Plot from '@/lib/charts/Plot';
import { CHART_COLORS } from '@/lib/charts/theme';
import {
  CHART_DATE_HOVERFORMAT,
  CHART_DATE_TICKFORMAT,
  CHART_MONEY_HOVERFORMAT,
  CHART_MONEY_TICKFORMAT,
  CHART_MONEY_TICKPREFIX,
  formatDate,
  formatDateTime,
  formatFraction,
  formatMoney,
  formatNumber,
  formatVol,
  nowMarketInput,
} from '@/lib/format';
import { STATE_LABEL } from '@/lib/edge/labels';
import { MODEL_LABEL } from '@/lib/forecast/labels';
import { entryFormSchema, instrumentsFor, toEntryCreate, voidable, USER_KINDS, type EntryFormValues } from '@/lib/journal/form';
import {
  CS04_HELP,
  DELTA_BAND_HELP,
  ENTRY_KIND_LABEL,
  ERROR_FLAG_HELP,
  EXECUTION_HELP,
  MARK_ORIGIN_HELP,
  MARK_ORIGIN_LABEL,
  RESIDUAL_HELP,
  STATUS_LABEL,
} from '@/lib/journal/labels';
import { STRUCTURE_LABEL } from '@/lib/simulator/labels';
import { problemMessage } from '@/lib/api/problem';
import styles from '../vol/vol.module.css';

/** Consultas que mudam com um lançamento (a operação, o diário e a carteira). */
function dependsOnEntries(key: readonly unknown[]): boolean {
  const id = (key[0] as { _id?: string } | undefined)?._id ?? '';
  return ['getPosition', 'listPositions', 'getPortfolio', 'getLimits'].includes(id);
}

/**
 * Operação (PRD 1.10 §8.1; RF-DIA-02..04, RS-06, CS-04): retrato da decisão, quantidades, lançamentos
 * (com estorno), marcação D-1 e atribuição diária com o resíduo sempre visível.
 */
export default function PositionView({ id }: { id: number }) {
  const { data, isPending, isError, refetch, isFetching } = useQuery(getPositionOptions({ path: { position_id: id } }));
  if (isError) return <p className={styles.error}>Operação não encontrada ou engine fora do ar.</p>;
  if (isPending) return <p className={styles.muted}>Carregando…</p>;
  return (
    <div className={styles.grid}>
      <Summary position={data} />
      <RiskFacts position={data} />
      <Attribution position={data} />
      <Marks position={data} />
      <Entries position={data} />
      <EntryForm position={data} />
      <p className={`${styles.muted} ${styles.small} ${styles.wide}`}>
        A marcação e a atribuição são refeitas pelo worker depois de cada lançamento e de cada coleta.{' '}
        <button type="button" className={styles.ghost} onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? 'Atualizando…' : 'Atualizar'}
        </button>
      </p>
    </div>
  );
}

function Summary({ position: p }: { position: PositionOut }) {
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="op-summary">
      <h2 id="op-summary" className={`${styles.eyebrow} mono`}>
        {STRUCTURE_LABEL[p.structure]} {p.ticker} · {STATUS_LABEL[p.status]}
      </h2>
      <dl className={styles.facts}>
        <dt>Lotes</dt>
        <dd>{formatNumber(p.lots)}</dd>
        <dt>Vencimento</dt>
        <dd>{formatDate(p.expiry)}</dd>
        <dt>Semáforo na entrada</dt>
        <dd data-testid="op-edge-state">
          {STATE_LABEL[p.edge_state]}
          {p.overridden && <span className={styles.tag} title={p.override_reason ?? ''}>override</span>}
        </dd>
        <dt>Modelo · configuração</dt>
        <dd>
          {MODEL_LABEL[p.model as keyof typeof MODEL_LABEL] ?? p.model} · v{p.config_version_id} · engine {p.engine_version}
        </dd>
        <dt>Registrada em</dt>
        <dd>{formatDateTime(p.created_at)}</dd>
        {p.rolled_from_position_id != null && (
          <>
            <dt>Rolada de</dt>
            <dd>
              <Link className={styles.link} href={`/app/operacoes/${p.rolled_from_position_id}`}>
                operação #{p.rolled_from_position_id}
              </Link>
            </dd>
          </>
        )}
        <dt>Quantidades atuais</dt>
        <dd data-testid="op-holdings">
          {p.holdings.length === 0
            ? '—'
            : p.holdings.map((h) => (
                <span key={h.instrument} className={styles.small}>
                  {h.instrument}: {formatNumber(h.quantity)}{' '}
                </span>
              ))}
        </dd>
      </dl>
      {p.ledger_error && (
        <p className={styles.error}>
          Lançamentos inconsistentes: {p.ledger_error}. A operação fica fora da carteira até a correção.
        </p>
      )}
      {p.pending_expiry.length > 0 && (
        <p className={styles.warn}>
          Vencida com quantidade em aberto: {p.pending_expiry.join(', ')}. Lance o exercício, a designação ou a saída a R$ 0
          (vencimento sem exercício) (LC-08).
        </p>
      )}
    </section>
  );
}

export function RiskFacts({ position: p }: { position: PositionOut }) {
  const band = p.delta_band;
  const cs = p.cs04;
  return (
    <section className={styles.card} aria-labelledby="op-risk">
      <h2 id="op-risk" className={`${styles.eyebrow} mono`}>
        Delta e resíduo
      </h2>
      <dl className={styles.facts}>
        <dt title={DELTA_BAND_HELP}>Banda de delta</dt>
        <dd data-testid="op-delta-band" data-state={band?.state}>
          {band == null || band.state === 'unavailable' ? (
            'sem marcação'
          ) : (
            <>
              {band.state === 'outside' ? (
                <strong className={styles.warn}>Fora da banda</strong>
              ) : (
                <span>Dentro da banda</span>
              )}{' '}
              · Δ {formatNumber(band.delta_shares, 1)} ações em {formatDate(band.as_of)} (± {formatNumber(band.half_width_shares, 1)})
              <span className={styles.tag} title={DELTA_BAND_HELP}>
                não calibrado
              </span>
            </>
          )}
        </dd>
        <dt title={CS04_HELP}>Resíduo (CS-04)</dt>
        <dd data-testid="op-cs04">
          {cs?.ratio == null ? (
            '—'
          ) : (
            <span className={cs.ok ? undefined : styles.warn}>
              {formatFraction(Math.min(cs.ratio, 1))}
              {cs.ratio > 1 ? '+' : ''} (meta &lt; {formatFraction(cs.target, 0)})
            </span>
          )}
        </dd>
        <dt title={ERROR_FLAG_HELP}>Dias com resíduo alto</dt>
        <dd>{formatNumber(cs?.error_days ?? 0)}</dd>
      </dl>
    </section>
  );
}

const PARTS: { key: keyof AttributionOut; label: string; color: string }[] = [
  { key: 'delta_brl', label: 'Delta', color: CHART_COLORS.series[0] },
  { key: 'gamma_brl', label: 'Gamma', color: CHART_COLORS.series[1] },
  { key: 'theta_brl', label: 'Theta', color: CHART_COLORS.series[2] },
  { key: 'vega_brl', label: 'Vega', color: CHART_COLORS.series[3] },
  { key: 'residual_brl', label: 'Resíduo', color: CHART_COLORS.danger },
];

export function Attribution({ position: p }: { position: PositionOut }) {
  const rows = p.attribution;
  const t = p.totals;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="op-attr">
      <h2 id="op-attr" className={`${styles.eyebrow} mono`}>
        Atribuição diária do P&amp;L (marcação D-1)
      </h2>
      {rows.length === 0 ? (
        <p className={styles.muted}>Sem marcação ainda: o worker marca depois da próxima coleta ou do próximo lançamento.</p>
      ) : (
        <>
          <Plot
            data={[
              ...PARTS.map((part) => ({
                type: 'bar' as const,
                name: part.label,
                x: rows.map((r) => r.trade_date),
                y: rows.map((r) => Number(r[part.key])),
                marker: { color: part.color },
              })),
              {
                type: 'scatter' as const,
                mode: 'markers' as const,
                name: 'Execução e custos',
                x: rows.map((r) => r.trade_date),
                y: rows.map((r) => Number(r.execution_brl)),
                marker: { color: CHART_COLORS.muted, symbol: 'diamond' },
              },
            ]}
            layout={{
              barmode: 'relative',
              xaxis: { type: 'date', tickformat: CHART_DATE_TICKFORMAT, hoverformat: CHART_DATE_HOVERFORMAT },
              yaxis: {
                tickprefix: CHART_MONEY_TICKPREFIX,
                tickformat: CHART_MONEY_TICKFORMAT,
                hoverformat: CHART_MONEY_HOVERFORMAT,
              },
            }}
            height={300}
            ariaLabel="Atribuição diária do P&L por delta, gamma, theta, vega e resíduo, e a execução e custos"
          />
          <div className={styles.tableWrap}>
            <table className={styles.table} data-testid="op-attribution">
              <thead>
                <tr>
                  <th scope="col">Pregão</th>
                  {PARTS.map((part) => (
                    <th key={part.key} scope="col" className={styles.num} title={part.key === 'residual_brl' ? RESIDUAL_HELP : undefined}>
                      {part.label}
                    </th>
                  ))}
                  <th scope="col" className={styles.num}>
                    Mercado
                  </th>
                  <th scope="col" className={styles.num} title={EXECUTION_HELP}>
                    Execução e custos
                  </th>
                  <th scope="col" className={styles.num}>
                    Total
                  </th>
                  <th scope="col">Avisos</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.trade_date}>
                    <td>{formatDate(r.trade_date)}</td>
                    {PARTS.map((part) => (
                      <td key={part.key} className={styles.num}>
                        {formatMoney(r[part.key] as string)}
                      </td>
                    ))}
                    <td className={styles.num}>{formatMoney(r.market_brl)}</td>
                    <td className={styles.num}>{formatMoney(r.execution_brl)}</td>
                    <td className={styles.num}>{formatMoney(r.total_brl)}</td>
                    <td>
                      {r.error_flag && (
                        <span className={styles.tag} title={ERROR_FLAG_HELP}>
                          resíduo alto
                        </span>
                      )}
                      {r.stale && <span className={styles.tag}>desatualizado</span>}
                    </td>
                  </tr>
                ))}
                {t && (
                  <tr>
                    <th scope="row">Acumulado</th>
                    {PARTS.map((part) => (
                      <td key={part.key} className={styles.num}>
                        <strong>{formatMoney(t[part.key as keyof typeof t])}</strong>
                      </td>
                    ))}
                    <td className={styles.num}>
                      <strong>{formatMoney(t.market_brl)}</strong>
                    </td>
                    <td className={styles.num}>
                      <strong>{formatMoney(t.execution_brl)}</strong>
                    </td>
                    <td className={styles.num}>
                      <strong>{formatMoney(t.total_brl)}</strong>
                    </td>
                    <td />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export function Marks({ position: p }: { position: PositionOut }) {
  if (p.marks.length === 0) return null;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="op-marks">
      <h2 id="op-marks" className={`${styles.eyebrow} mono`}>
        Marcação D-1
      </h2>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Pregão</th>
              <th scope="col" className={styles.num}>
                Ativo
              </th>
              <th scope="col" className={styles.num}>
                Ações
              </th>
              <th scope="col" className={styles.num}>
                Opções (valor)
              </th>
              <th scope="col" className={styles.num}>
                Delta (ações)
              </th>
              <th scope="col" className={styles.num}>
                Vega por ponto
              </th>
              <th scope="col" className={styles.num}>
                Theta por du
              </th>
              <th scope="col">Pernas</th>
            </tr>
          </thead>
          <tbody>
            {p.marks.map((m) => (
              <tr key={m.trade_date}>
                <td>{formatDate(m.trade_date)}</td>
                <td className={styles.num}>{formatMoney(m.spot_brl)}</td>
                <td className={styles.num}>{formatNumber(m.stock_qty)}</td>
                <td className={styles.num}>{formatMoney(m.options_value_brl)}</td>
                <td className={styles.num}>{formatNumber(m.delta_shares, 1)}</td>
                <td className={styles.num}>{formatMoney(m.vega_per_point_brl)}</td>
                <td className={styles.num}>{formatMoney(m.theta_per_bd_brl)}</td>
                <td>
                  {m.legs
                    .filter((l) => l.quantity !== 0)
                    .map((l) => (
                      <div key={l.code} className={styles.small}>
                        {l.code} {formatNumber(l.quantity)} × {formatMoney(l.price_brl)} · IV {formatVol(l.iv)}
                        {l.origin !== 'observed' && (
                          <span className={styles.tag} title={MARK_ORIGIN_HELP[l.origin]}>
                            {MARK_ORIGIN_LABEL[l.origin]}
                          </span>
                        )}
                      </div>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function Entries({ position: p }: { position: PositionOut }) {
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="op-entries">
      <h2 id="op-entries" className={`${styles.eyebrow} mono`}>
        Lançamentos
      </h2>
      <div className={styles.tableWrap}>
        <table className={styles.table} data-testid="op-entries">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Tipo</th>
              <th scope="col">Instrumento</th>
              <th scope="col" className={styles.num}>
                Quantidade
              </th>
              <th scope="col" className={styles.num}>
                Preço
              </th>
              <th scope="col" className={styles.num}>
                Taxas + corretagem
              </th>
              <th scope="col">Executado em</th>
              <th scope="col">Observação</th>
            </tr>
          </thead>
          <tbody>
            {p.entries.map((e) => (
              <tr key={e.id} className={e.voided_by != null ? styles.muted : undefined}>
                <td>{formatNumber(e.id)}</td>
                <td>
                  {ENTRY_KIND_LABEL[e.kind]}
                  {e.voided_by != null && <span className={styles.tag}>estornado por #{e.voided_by}</span>}
                </td>
                <td>{e.instrument}</td>
                <td className={styles.num}>{formatNumber(e.quantity)}</td>
                <td className={styles.num}>{formatMoney(e.price_brl)}</td>
                <td className={styles.num}>{formatMoney(Number(e.fees_brl) + Number(e.brokerage_brl))}</td>
                <td>{formatDateTime(e.executed_at)}</td>
                <td className={styles.small}>
                  {e.kind === 'void' && `anula #${e.linked_entry_id}: ${e.void_reason ?? ''}`}
                  {e.strike_after_brl != null && `novo strike ${formatMoney(e.strike_after_brl)}`}
                  {e.note ? ` ${e.note}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const KIND_HELP: Record<(typeof USER_KINDS)[number], string> = {
  hedge: 'Ação do ativo-objeto, com sinal: + compra, − venda.',
  exit: 'Reduz a perna até zero (parcial ou total). Opção que venceu sem valor: saída a R$ 0.',
  exercise: 'Perna comprada: quantidade negativa (opções exercidas) e o strike efetivo no preço.',
  assignment: 'Perna vendida: quantidade positiva (opções designadas) e o strike efetivo no preço.',
  strike_adjustment: 'Quantidade da perna depois do ajuste (mesmo sinal) e o novo strike efetivo, conforme o aviso da B3.',
  void: 'Anula um lançamento anterior; o original fica no histórico. Motivo obrigatório.',
};

function EntryForm({ position: p }: { position: PositionOut }) {
  const queryClient = useQueryClient();
  const form = useForm<EntryFormValues>({
    resolver: zodResolver(entryFormSchema),
    defaultValues: {
      kind: 'hedge',
      instrument: p.ticker,
      quantity: '',
      price: '',
      fees: '',
      strikeAfter: '',
      linkedEntryId: '',
      voidReason: '',
      executedAt: nowMarketInput(),
      note: '',
    },
  });
  const kind = useWatch({ control: form.control, name: 'kind' });
  const save = useMutation({
    ...postEntryMutation(),
    onSuccess: () => {
      form.reset({ ...form.getValues(), quantity: '', price: '', fees: '', voidReason: '', note: '' });
      return queryClient.invalidateQueries({ predicate: (q) => dependsOnEntries(q.queryKey) });
    },
  });
  const errors = form.formState.errors;
  const instruments = instrumentsFor(kind, p.ticker, p.holdings);
  const canVoid = voidable(p.entries);
  if (p.status === 'closed' && canVoid.length === 0) return null;

  const onSubmit = form.handleSubmit((values) => {
    save.mutate({ path: { position_id: p.id }, body: toEntryCreate(values) });
  });

  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="op-new-entry">
      <h2 id="op-new-entry" className={`${styles.eyebrow} mono`}>
        Novo lançamento
      </h2>
      <p className={`${styles.muted} ${styles.small}`}>{KIND_HELP[kind]}</p>
      <form className={styles.form} onSubmit={onSubmit} noValidate aria-label="Novo lançamento">
        <label className={styles.field}>
          <span>Tipo</span>
          <select
            className={styles.select}
            {...form.register('kind', {
              onChange: (e: { target: { value: string } }) => {
                const next = e.target.value as (typeof USER_KINDS)[number];
                form.setValue('instrument', instrumentsFor(next, p.ticker, p.holdings)[0] ?? '');
              },
            })}
          >
            {USER_KINDS.filter((k) => p.status === 'open' || k === 'void').map((k) => (
              <option key={k} value={k}>
                {ENTRY_KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        {kind === 'void' ? (
          <>
            <label className={styles.field}>
              <span>Lançamento a estornar</span>
              <select className={styles.select} {...form.register('linkedEntryId')}>
                <option value="">Escolha…</option>
                {canVoid.map((e) => (
                  <option key={e.id} value={e.id}>
                    #{e.id} {ENTRY_KIND_LABEL[e.kind]} {e.instrument} {formatNumber(e.quantity)}
                  </option>
                ))}
              </select>
              {errors.linkedEntryId && <span className={styles.fieldError}>{errors.linkedEntryId.message}</span>}
            </label>
            <label className={styles.field}>
              <span>Motivo do estorno</span>
              <input className={styles.input} {...form.register('voidReason')} />
              {errors.voidReason && <span className={styles.fieldError}>{errors.voidReason.message}</span>}
            </label>
          </>
        ) : (
          <>
            <label className={styles.field}>
              <span>Instrumento</span>
              <select className={styles.select} {...form.register('instrument')}>
                {instruments.length === 0 && <option value="">nenhum elegível</option>}
                {instruments.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
              {errors.instrument && <span className={styles.fieldError}>{errors.instrument.message}</span>}
            </label>
            <label className={styles.field}>
              <span>{kind === 'strike_adjustment' ? 'Quantidade depois do ajuste' : 'Quantidade (+ compra, − venda)'}</span>
              <input className={styles.input} inputMode="numeric" {...form.register('quantity')} />
              {errors.quantity && <span className={styles.fieldError}>{errors.quantity.message}</span>}
            </label>
            <label className={styles.field}>
              <span>{kind === 'exercise' || kind === 'assignment' ? 'Strike efetivo (R$)' : 'Preço executado (R$)'}</span>
              <input className={styles.input} inputMode="decimal" {...form.register('price')} />
              {errors.price && <span className={styles.fieldError}>{errors.price.message}</span>}
            </label>
            {kind === 'strike_adjustment' && (
              <label className={styles.field}>
                <span>Novo strike efetivo (R$)</span>
                <input className={styles.input} inputMode="decimal" {...form.register('strikeAfter')} />
                {errors.strikeAfter && <span className={styles.fieldError}>{errors.strikeAfter.message}</span>}
              </label>
            )}
            <label className={styles.field}>
              <span>Taxas e corretagem (R$)</span>
              <input className={styles.input} inputMode="decimal" placeholder="0" {...form.register('fees')} />
              {errors.fees && <span className={styles.fieldError}>{errors.fees.message}</span>}
            </label>
          </>
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
        <div>
          <button type="submit" className={styles.button} disabled={save.isPending}>
            {save.isPending ? 'Lançando…' : 'Lançar'}
          </button>
        </div>
      </form>
      {save.isError && <p className={styles.error}>{problemMessage(save.error, 'Não foi possível lançar.')}</p>}
      {save.isSuccess && <p role="status">Lançamento gravado. A marcação é refeita pelo worker.</p>}
    </section>
  );
}
