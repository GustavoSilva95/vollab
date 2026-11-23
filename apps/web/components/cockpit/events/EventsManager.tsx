'use client';

import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { EventOut } from '@vollab/api-types';
import {
  createEventMutation,
  deleteEventMutation,
  listEventsQueryKey,
  listEventsOptions,
  listUnderlyingsOptions,
  updateEventMutation,
} from '@vollab/api-types/react-query';
import { eventFormSchema, toEventCreate, type EventFormValues } from '@/lib/events/form';
import { formatDate, formatMoney } from '@/lib/format';
import { EDITABLE_EVENT_KINDS, EVENT_KIND_LABEL } from '@/lib/vol/labels';
import styles from '../vol/vol.module.css';

const EMPTY_FORM: EventFormValues = {
  kind: 'earnings',
  ticker: '',
  event_date: '',
  status: 'estimated',
  amount: '',
  note: '',
};

function problemMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  return 'Não foi possível salvar. Confira os campos e tente de novo.';
}

/**
 * Calendário de eventos (RF-EVT-01/02, PRD §8.1): cadastro manual, confirmado ou estimado.
 * Vencimentos vêm das séries e não são editáveis. Ex-dividendo e ex-JCP levam o valor por ação e
 * entram no ajuste dos retornos e na precificação (o worker recalcula o ativo).
 */
export default function EventsManager() {
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState<string>('');
  const query = ticker ? { ticker } : undefined;
  const events = useQuery(listEventsOptions({ query }));
  const underlyings = useQuery(listUnderlyingsOptions());
  const invalidate = () => queryClient.invalidateQueries({ queryKey: listEventsQueryKey() });
  const create = useMutation({ ...createEventMutation(), onSuccess: invalidate });
  const update = useMutation({ ...updateEventMutation(), onSuccess: invalidate });
  const remove = useMutation({ ...deleteEventMutation(), onSuccess: invalidate });

  const form = useForm<EventFormValues>({ resolver: zodResolver(eventFormSchema), defaultValues: EMPTY_FORM });
  const kind = useWatch({ control: form.control, name: 'kind' });
  const withAmount = kind === 'ex_dividend' || kind === 'ex_jcp';
  const marketWide = kind === 'copom' || kind === 'macro';

  const onSubmit = form.handleSubmit((values) =>
    create.mutate({ body: toEventCreate(values) }, { onSuccess: () => form.reset({ ...EMPTY_FORM, kind: values.kind }) }),
  );

  const errors = form.formState.errors;
  const mutationError = create.error ?? update.error ?? remove.error;

  return (
    <div className={styles.grid}>
      <section className={`${styles.card} ${styles.wide}`} aria-labelledby="new-event-title">
        <h2 id="new-event-title" className={`${styles.eyebrow} mono`}>
          Novo evento
        </h2>
        <form className={styles.form} onSubmit={onSubmit} noValidate>
          <label className={styles.field}>
            Tipo
            <select className={styles.select} {...form.register('kind')}>
              {EDITABLE_EVENT_KINDS.map((k) => (
                <option key={k} value={k}>
                  {EVENT_KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            Ativo
            <select className={styles.select} {...form.register('ticker')} disabled={marketWide}>
              <option value="">{marketWide ? 'mercado (sem ativo)' : 'escolha…'}</option>
              {underlyings.data?.map((u) => (
                <option key={u.ticker} value={u.ticker}>
                  {u.ticker}
                </option>
              ))}
            </select>
            {errors.ticker && <span className={styles.fieldError}>{errors.ticker.message}</span>}
          </label>
          <label className={styles.field}>
            Data (pregão afetado)
            <input type="date" className={styles.input} {...form.register('event_date')} />
            {errors.event_date && <span className={styles.fieldError}>{errors.event_date.message}</span>}
          </label>
          <label className={styles.field}>
            Situação
            <select className={styles.select} {...form.register('status')}>
              <option value="estimated">estimada</option>
              <option value="confirmed">confirmada</option>
            </select>
          </label>
          {withAmount && (
            <label className={styles.field}>
              Valor por ação (R$)
              <input inputMode="decimal" placeholder="0,85" className={styles.input} {...form.register('amount')} />
              {errors.amount && <span className={styles.fieldError}>{errors.amount.message}</span>}
            </label>
          )}
          <label className={styles.field}>
            Nota
            <input className={styles.input} maxLength={500} {...form.register('note')} />
          </label>
          <div>
            <button type="submit" className={styles.button} disabled={create.isPending}>
              {create.isPending ? 'Salvando…' : 'Cadastrar'}
            </button>
          </div>
        </form>
        <p className={`${styles.muted} ${styles.small}`} style={{ marginTop: 12 }}>
          Resultado: informe o pregão cujo retorno contém o evento (divulgação após o fechamento → pregão seguinte).
          Ex-dividendo/ex-JCP: o valor ajusta os retornos (RN-VOL-07) e a precificação; o recálculo roda no worker.
        </p>
        {mutationError && (
          <p className={styles.error} role="alert">
            {problemMessage(mutationError)}
          </p>
        )}
      </section>

      <section className={`${styles.card} ${styles.wide}`} aria-labelledby="events-title" aria-busy={events.isPending}>
        <h2 id="events-title" className={`${styles.eyebrow} mono`}>
          Calendário
        </h2>
        <div className={styles.controls}>
          <label className={styles.field} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            Ativo
            <select className={styles.select} value={ticker} onChange={(e) => setTicker(e.target.value)}>
              <option value="">todos</option>
              {underlyings.data?.map((u) => (
                <option key={u.ticker} value={u.ticker}>
                  {u.ticker}
                </option>
              ))}
            </select>
          </label>
        </div>
        {events.isError && <p className={styles.error}>Não foi possível carregar os eventos.</p>}
        {events.data && events.data.length === 0 && <p className={styles.muted}>Nenhum evento no período.</p>}
        {events.data && events.data.length > 0 && (
          <EventsTable
            events={events.data}
            busy={update.isPending || remove.isPending}
            onToggle={(e) =>
              update.mutate({
                path: { event_id: e.id as number },
                body: { status: e.status === 'confirmed' ? 'estimated' : 'confirmed' },
              })
            }
            onDelete={(e) => remove.mutate({ path: { event_id: e.id as number } })}
          />
        )}
      </section>
    </div>
  );
}

function EventsTable({
  events,
  busy,
  onToggle,
  onDelete,
}: {
  events: EventOut[];
  busy: boolean;
  onToggle: (e: EventOut) => void;
  onDelete: (e: EventOut) => void;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Data</th>
            <th scope="col">Ativo</th>
            <th scope="col">Tipo</th>
            <th scope="col">Situação</th>
            <th scope="col" className={styles.num}>
              Valor
            </th>
            <th scope="col">Nota</th>
            <th scope="col">
              <span className="sr-only">Ações</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id ?? `${e.ticker}:${e.kind}:${e.event_date}`}>
              <td>{formatDate(e.event_date)}</td>
              <td className="mono">{e.ticker ?? <span className={styles.muted}>mercado</span>}</td>
              <td>
                {EVENT_KIND_LABEL[e.kind]}
                {e.derived && (
                  <span className={styles.tag} title="Derivado das séries do COTAHIST; não editável.">
                    séries
                  </span>
                )}
              </td>
              <td>{e.status === 'confirmed' ? 'confirmada' : 'estimada'}</td>
              <td className={styles.num}>{e.amount ? formatMoney(e.amount, 4) : ''}</td>
              <td className={styles.muted}>{e.note}</td>
              <td style={{ whiteSpace: 'nowrap' }}>
                {!e.derived && (
                  <>
                    <button type="button" className={styles.ghost} disabled={busy} onClick={() => onToggle(e)}>
                      {e.status === 'confirmed' ? 'Marcar estimada' : 'Confirmar'}
                    </button>{' '}
                    <button
                      type="button"
                      className={styles.ghost}
                      disabled={busy}
                      onClick={() => onDelete(e)}
                      aria-label={`Apagar ${EVENT_KIND_LABEL[e.kind]} de ${formatDate(e.event_date)}`}
                    >
                      Apagar
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
