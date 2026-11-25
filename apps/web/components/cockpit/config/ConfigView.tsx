'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ConfigVersionOut } from '@vollab/api-types';
import {
  getConfigOptions,
  getConfigVersionOptions,
  listConfigVersionsOptions,
  getCrisisOptions,
  postConfigMutation,
  postCrisisMeasureMutation,
} from '@vollab/api-types/react-query';
import {
  BLOCK_LABEL,
  FIELDS,
  FIELD_NAMES,
  configFormSchema,
  diffParams,
  toConfigParams,
  toFormValues,
  type ConfigFormValues,
  type FieldName,
} from '@/lib/config/form';
import { formatDate, formatDateTime, formatNumber, formatReturn, formatVolShock } from '@/lib/format';
import { NOT_CALIBRATED_HELP } from '@/lib/edge/labels';
import { CRISIS_HELP } from '@/lib/journal/labels';
import styles from '../vol/vol.module.css';

const BLOCKS = ['costs', 'edge', 'vol', 'forecast', 'risk', 'journal'] as const;

function problemMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  return 'Não foi possível salvar. Confira os campos e tente de novo.';
}

/** Consultas que dependem da configuração (ranking, previsão, modelos) e o histórico de versões. */
function dependsOnConfig(key: readonly unknown[]): boolean {
  const id = (key[0] as { _id?: string } | undefined)?._id ?? '';
  return [
    'getConfig',
    'listConfigVersions',
    'getRanking',
    'getForecasts',
    'getModelsEvaluation',
    'getPortfolio',
    'getLimits',
    'getCrisis',
    'getPosition',
  ].includes(id);
}

/**
 * Configuração versionada (PRD 1.8 §8.1; BRD §7.11): editar cria uma versão nova, nunca altera uma
 * existente. Custos e edge valem na hora no ranking; parâmetros marcados valem no próximo recálculo.
 */
export default function ConfigView() {
  const { data, isPending, isError } = useQuery(getConfigOptions());
  // A mensagem fica aqui: salvar troca a versão vigente e remonta o formulário (key = id).
  const [saved, setSaved] = useState<string | null>(null);
  if (isError) return <p className={styles.error}>Não foi possível ler a configuração. O engine está no ar?</p>;
  if (isPending) return <p className={styles.muted}>Carregando…</p>;
  return (
    <div className={styles.grid}>
      <ConfigForm key={data.id} current={data} saved={saved} onSaved={setSaved} />
      <CrisisPanel />
      <VersionHistory />
    </div>
  );
}

export function ConfigForm({
  current,
  saved,
  onSaved,
}: {
  current: ConfigVersionOut;
  saved: string | null;
  onSaved: (message: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const form = useForm<ConfigFormValues>({
    resolver: zodResolver(configFormSchema),
    defaultValues: toFormValues(current.params),
  });
  const save = useMutation({
    ...postConfigMutation(),
    onSuccess: (out) => {
      onSaved(out.created ? `Versão ${formatNumber(out.id)} criada.` : 'Nada mudou: nenhuma versão criada.');
      if (!out.created) return;
      return queryClient.invalidateQueries({ predicate: (q) => dependsOnConfig(q.queryKey) });
    },
  });
  const onSubmit = form.handleSubmit((values) => {
    onSaved(null);
    save.mutate({
      body: { params: toConfigParams(values, current.params), note: values.note.trim(), base_version_id: current.id },
    });
  });
  const errors = form.formState.errors;

  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="cfg-title">
      <h2 id="cfg-title" className={`${styles.eyebrow} mono`}>
        Parâmetros — versão vigente {formatNumber(current.id)}
      </h2>
      <p className={styles.muted}>
        Salvar cria uma versão nova (as antigas ficam no histórico e nas decisões que as usaram). Campos com
        <span className={styles.tag}>próximo recálculo</span> só valem depois da próxima coleta ou recálculo; o histórico
        gravado não é refeito.
      </p>
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {BLOCKS.map((b) => (
          <fieldset key={b} className={styles.form}>
            <legend className={`${styles.eyebrow} mono`}>{BLOCK_LABEL[b]}</legend>
            {FIELD_NAMES.filter((n) => FIELDS[n].block === b).map((name) => (
              <Field key={name} name={name} form={form} error={errors[name]?.message} />
            ))}
            {b === 'costs' && (
              <div className={styles.field}>
                <span>Faixas de moneyness K/F (baixa | ATM | alta)</span>
                <span>
                  <input className={styles.input} aria-label="Limite inferior da faixa ATM" {...form.register('band_low')} />{' '}
                  <input className={styles.input} aria-label="Limite superior da faixa ATM" {...form.register('band_high')} />
                  <span className={styles.tag}>próximo recálculo</span>
                </span>
                {errors.band_high && <span className={styles.fieldError}>{errors.band_high.message}</span>}
              </div>
            )}
            {b === 'risk' && (
              <div className={styles.field}>
                <label htmlFor="cfg-capital">Capital alocado para opções (R$)</label>
                <input id="cfg-capital" className={styles.input} inputMode="decimal" placeholder="não informado" {...form.register('capital')} />
                <span className={`${styles.muted} ${styles.small}`}>
                  Base dos limites e do dimensionamento (RN-SIZ-01). Vazio: limites indisponíveis.
                </span>
                {errors.capital && <span className={styles.fieldError}>{errors.capital.message}</span>}
              </div>
            )}
          </fieldset>
        ))}
        <label className={styles.field}>
          <span>Nota da versão</span>
          <input className={styles.input} placeholder="O que mudou e por quê" {...form.register('note')} />
          {errors.note && <span className={styles.fieldError}>{errors.note.message}</span>}
        </label>
        <div>
          <button type="submit" className={styles.button} disabled={save.isPending}>
            Salvar nova versão
          </button>{' '}
          <button
            type="button"
            className={styles.ghost}
            onClick={() => form.reset(toFormValues(current.params))}
            disabled={save.isPending}
          >
            Descartar
          </button>
        </div>
        {save.isError && <p className={styles.error}>{problemMessage(save.error)}</p>}
        {saved && <p role="status">{saved}</p>}
      </form>
    </section>
  );
}

function Field({
  name,
  form,
  error,
}: {
  name: FieldName;
  form: ReturnType<typeof useForm<ConfigFormValues>>;
  error: string | undefined;
}) {
  const spec = FIELDS[name];
  const id = `cfg-${name}`;
  return (
    <div className={styles.field}>
      <label htmlFor={id}>
        {spec.label}
        {'verify' in spec && spec.verify && (
          <span className={styles.tag} title="Valor padrão a conferir na tabela de tarifas vigente da B3.">
            a conferir
          </span>
        )}
        {'nextRecompute' in spec && spec.nextRecompute && <span className={styles.tag}>próximo recálculo</span>}
        {'uncalibrated' in spec && spec.uncalibrated && (
          <span className={styles.tag} title={NOT_CALIBRATED_HELP}>
            não calibrado
          </span>
        )}
      </label>
      <input id={id} className={styles.input} inputMode="decimal" aria-invalid={error != null} {...form.register(name)} />
      {'help' in spec && spec.help && <span className={`${styles.muted} ${styles.small}`}>{spec.help}</span>}
      {error && <span className={styles.fieldError}>{error}</span>}
    </div>
  );
}

function CrisisPanel() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ ...getCrisisOptions(), refetchInterval: (q) => (q.state.data?.job ? 5000 : false) });
  const measure = useMutation({
    ...postCrisisMeasureMutation(),
    onSuccess: () => queryClient.invalidateQueries({ predicate: (q) => dependsOnConfig(q.queryKey) }),
  });
  if (!data) return null;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="crisis-title">
      <h2 id="crisis-title" className={`${styles.eyebrow} mono`}>
        Cenários de crise (QA-12)
      </h2>
      <p className={`${styles.muted} ${styles.small}`}>{CRISIS_HELP}</p>
      <p className={styles.small}>
        Episódios:{' '}
        {data.episodes.map((e) => `${e.label} (${formatDate(e.start)} a ${formatDate(e.end)})`).join('; ')} · janela de{' '}
        {formatNumber(data.horizon_bd)} pregões.
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table} data-testid="crisis-table">
          <thead>
            <tr>
              <th scope="col">Ativo</th>
              <th scope="col">Episódio</th>
              <th scope="col">Janela</th>
              <th scope="col" className={styles.num}>
                Choque no ativo
              </th>
              <th scope="col" className={styles.num}>
                Choque de vol
              </th>
              <th scope="col">Método · origem</th>
            </tr>
          </thead>
          <tbody>
            {data.values.map((v) => (
              <tr key={`${v.ticker}-${v.episode}`}>
                <td>{v.ticker}</td>
                <td>{v.label}</td>
                <td>{v.window_start ? `${formatDate(v.window_start)} a ${formatDate(v.window_end)}` : '—'}</td>
                <td className={styles.num}>{v.status === 'ok' ? formatReturn(v.price_shock, 1) : '—'}</td>
                <td className={styles.num}>{v.status === 'ok' ? formatVolShock(v.vol_shock) : '—'}</td>
                <td className={styles.small}>
                  {v.status === 'ok' ? (
                    <>
                      {v.origin === 'manual' ? 'manual' : v.vol_method === 'atm_iv' ? 'IV ATM dos fechamentos' : 'RV de 20 pregões'}
                      <span className={styles.tag}>{v.origin === 'manual' ? 'manual' : 'aproximado'}</span>
                    </>
                  ) : (
                    <span className={styles.warn}>indisponível</span>
                  )}
                  {v.reason ? ` ${v.reason}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <button
          type="button"
          className={styles.button}
          onClick={() => measure.mutate({})}
          disabled={measure.isPending || data.job != null}
        >
          {data.job ? 'Medindo no worker…' : 'Medir cenários de crise'}
        </button>{' '}
        <span className={`${styles.muted} ${styles.small}`}>
          Baixa uma vez os COTAHIST anuais de 2017 e 2020 (dezenas de MB) no worker; anos passados ficam no cache bruto.
        </span>
      </p>
      {measure.isError && <p className={styles.error}>{problemMessage(measure.error)}</p>}
    </section>
  );
}

function VersionHistory() {
  const { data } = useQuery(listConfigVersionsOptions());
  const [selected, setSelected] = useState<number | null>(null);
  if (!data) return null;
  const index = selected == null ? -1 : data.findIndex((v) => v.id === selected);
  const previous = index >= 0 ? data[index + 1] : undefined;
  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="hist-title">
      <h2 id="hist-title" className={`${styles.eyebrow} mono`}>
        Histórico de versões
      </h2>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Versão</th>
              <th scope="col">Criada em</th>
              <th scope="col">Nota</th>
              <th scope="col">
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((v) => (
              <tr key={v.id}>
                <th scope="row">
                  {formatNumber(v.id)}
                  {v.current && <span className={styles.official}>vigente</span>}
                </th>
                <td>{formatDateTime(v.created_at)}</td>
                <td>{v.note ?? '—'}</td>
                <td>
                  <button type="button" className={styles.ghost} onClick={() => setSelected(v.id === selected ? null : v.id)}>
                    {v.id === selected ? 'Fechar' : 'Ver mudanças'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected != null && <VersionDiff id={selected} previousId={previous?.id ?? null} />}
    </section>
  );
}

function VersionDiff({ id, previousId }: { id: number; previousId: number | null }) {
  const after = useQuery(getConfigVersionOptions({ path: { version_id: id } }));
  const before = useQuery({
    ...getConfigVersionOptions({ path: { version_id: previousId ?? 0 } }),
    enabled: previousId != null,
  });
  if (!after.data || (previousId != null && !before.data)) return <p className={styles.muted}>Carregando…</p>;
  if (previousId == null) return <p className={styles.muted}>Primeira versão: valores padrão.</p>;
  const changes = diffParams(before.data?.params, after.data.params);
  return (
    <div className={styles.tableWrap}>
      <p className={styles.muted}>
        Mudanças da versão {formatNumber(previousId)} para a {formatNumber(id)} (valores como gravados: decimais).
      </p>
      {changes.length === 0 ? (
        <p className={styles.muted}>Nenhuma diferença de parâmetro.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Parâmetro</th>
              <th scope="col">Antes</th>
              <th scope="col">Depois</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((c) => (
              <tr key={c.path}>
                <th scope="row" className="mono">
                  {c.path}
                </th>
                <td className="mono">{c.before}</td>
                <td className="mono">{c.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
