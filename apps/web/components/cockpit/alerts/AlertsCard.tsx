'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAlertsOptions } from '@vollab/api-types/react-query';
import { formatNumber } from '@/lib/format';
import vol from '../vol/vol.module.css';
import AlertsList from './AlertsList';

/** Intervalo de releitura: o job de alertas roda no worker depois de cada coleta e lançamento. */
const REFRESH_MS = 15_000;

/**
 * Alertas do painel (PRD 1.11 §8.1; PRD-UI-10): não resolvidos ao abrir e depois de cada coleta, com
 * o histórico dos resolvidos sob demanda. Nenhuma notificação externa.
 */
export default function AlertsCard() {
  const [history, setHistory] = useState(false);
  const { data, isPending, isError } = useQuery({
    ...getAlertsOptions({ query: { state: history ? 'resolved' : 'open' } }),
    refetchInterval: REFRESH_MS,
  });
  return (
    <section className={`${vol.card} ${vol.wide}`} aria-labelledby="dash-alerts" data-testid="dash-alerts">
      <h2 id="dash-alerts" className={`${vol.eyebrow} mono`}>
        Alertas
        {data && (
          <>
            {' '}
            · {formatNumber(data.counts.active)} ativo(s) · {formatNumber(data.counts.seen)} visto(s)
          </>
        )}
      </h2>
      <p className={`${vol.muted} ${vol.small}`}>
        Hedge, saída, rolagem, limites e proventos, avaliados pelo worker depois de cada marcação D-1. Os parâmetros
        ficam em Configurações.{' '}
        <button type="button" className={vol.ghost} onClick={() => setHistory((h) => !h)}>
          {history ? 'Ver os não resolvidos' : 'Ver os resolvidos'}
        </button>
      </p>
      {isError && <p className={vol.error}>Não foi possível ler os alertas. O engine está no ar?</p>}
      {isPending && <p className={vol.muted}>Carregando…</p>}
      {data && <AlertsList alerts={data.alerts} />}
    </section>
  );
}
