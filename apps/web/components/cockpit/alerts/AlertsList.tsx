'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { AlertOut } from '@vollab/api-types';
import { patchAlertMutation } from '@vollab/api-types/react-query';
import {
  ALERT_STATE_LABEL,
  KIND_LABEL,
  RULE_HELP,
  RULE_LABEL,
  describeSafe,
  uncalibrated,
} from '@/lib/alerts/labels';
import { NOT_CALIBRATED_HELP } from '@/lib/edge/labels';
import { formatDate } from '@/lib/format';
import { STRUCTURE_LABEL } from '@/lib/simulator/labels';
import { problemMessage } from '@/lib/api/problem';
import { rollHref } from '@/lib/simulator/roll';
import vol from '../vol/vol.module.css';
import styles from './alerts.module.css';

/** Consultas que mudam com a transição de um alerta. */
export function dependsOnAlerts(key: readonly unknown[]): boolean {
  const id = (key[0] as { _id?: string } | undefined)?._id ?? '';
  return ['getAlerts', 'getPosition'].includes(id);
}

/**
 * Lista de alertas (PRD 1.11 §5.10 e §8.1; RN-GES-07, PRD-UI-10): tipo e estado com cor e texto,
 * números do disparo, rótulo "não calibrado", "marcar como visto" e "resolver" com nota opcional.
 */
export default function AlertsList({ alerts, showPosition = true }: { alerts: AlertOut[]; showPosition?: boolean }) {
  if (alerts.length === 0) return <p className={vol.muted}>Nenhum alerta.</p>;
  return (
    <ul className={styles.list} data-testid="alerts-list">
      {alerts.map((a) => (
        <AlertItem key={a.id} alert={a} showPosition={showPosition} />
      ))}
    </ul>
  );
}

export function AlertItem({ alert: a, showPosition }: { alert: AlertOut; showPosition: boolean }) {
  const queryClient = useQueryClient();
  const [resolving, setResolving] = useState(false);
  const [note, setNote] = useState('');
  const patch = useMutation({
    ...patchAlertMutation(),
    onSuccess: () => queryClient.invalidateQueries({ predicate: (q) => dependsOnAlerts(q.queryKey) }),
  });
  const details = a.details as Record<string, unknown>;
  return (
    <li className={styles.item} data-state={a.state} data-rule={a.rule} data-testid={`alert-${a.rule}`}>
      <div className={styles.head}>
        <span className={styles.kind} data-kind={a.kind}>
          {KIND_LABEL[a.kind]}
        </span>
        <span className={styles.rule} title={RULE_HELP[a.rule]}>
          {RULE_LABEL[a.rule]}
        </span>
        {uncalibrated(a.rule) && (
          <span className={vol.tag} title={NOT_CALIBRATED_HELP}>
            não calibrado
          </span>
        )}
        <span className={vol.state} data-testid="alert-state">
          {ALERT_STATE_LABEL[a.state]}
        </span>
        {showPosition && a.position_id != null && (
          <Link className={vol.link} href={`/app/operacoes/${a.position_id}`}>
            {a.structure ? STRUCTURE_LABEL[a.structure as keyof typeof STRUCTURE_LABEL] ?? a.structure : 'Operação'}{' '}
            {a.ticker} #{a.position_id}
          </Link>
        )}
        {a.position_id == null && <span className={styles.meta}>Carteira</span>}
      </div>
      <p>{describeSafe(a.rule, details)}</p>
      <p className={styles.meta}>
        Disparado no pregão {formatDate(a.triggered_as_of)}
        {a.last_as_of !== a.triggered_as_of && <> · avaliado até {formatDate(a.last_as_of)}</>} · configuração v
        {a.config_version_id}
        {a.evaluated_config_version_id !== a.config_version_id && <> (avaliado com v{a.evaluated_config_version_id})</>}
        {a.resolved_by && (
          <>
            {' '}
            · resolvido {a.resolved_by === 'auto' ? 'automaticamente' : 'pelo usuário'}
            {a.resolution_note ? `: ${a.resolution_note}` : ''}
          </>
        )}
      </p>
      {a.rule === 'roll_suggested' && a.position_id != null && (() => {
        const href = rollHref(a.ticker, a.position_id, details.expiry, a.structure);
        return href ? (
          <p>
            <Link className={vol.link} data-testid="alert-roll-link" href={href}>
              Abrir a rolagem no simulador
            </Link>
          </p>
        ) : null;
      })()}
      {a.state !== 'resolved' && (
        <div className={styles.actions}>
          {a.state === 'active' && (
            <button
              type="button"
              className={vol.ghost}
              disabled={patch.isPending}
              onClick={() => patch.mutate({ path: { alert_id: a.id }, body: { state: 'seen' } })}
            >
              Marcar como visto
            </button>
          )}
          {resolving ? (
            <form
              className={styles.actions}
              onSubmit={(e) => {
                e.preventDefault();
                patch.mutate({
                  path: { alert_id: a.id },
                  body: { state: 'resolved', ...(note.trim() ? { note: note.trim() } : {}) },
                });
              }}
            >
              <input
                className={vol.input}
                aria-label="Nota da resolução"
                placeholder="nota (opcional)"
                maxLength={500}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <button type="submit" className={vol.button} disabled={patch.isPending}>
                Confirmar
              </button>
              <button type="button" className={vol.ghost} onClick={() => setResolving(false)}>
                Cancelar
              </button>
            </form>
          ) : (
            <button type="button" className={vol.ghost} disabled={patch.isPending} onClick={() => setResolving(true)}>
              Resolver
            </button>
          )}
        </div>
      )}
      {a.state !== 'resolved' && (
        <p className={styles.meta}>
          Resolver com a condição ainda valendo não reabre o alerta até ela sumir e voltar.
        </p>
      )}
      {patch.isError && <p className={vol.error}>{problemMessage(patch.error, 'Não foi possível atualizar o alerta.')}</p>}
    </li>
  );
}
