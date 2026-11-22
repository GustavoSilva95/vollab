'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import type { CollectionPendingResponse } from '@vollab/api-types';
import { getCollectionPendingOptions } from '@vollab/api-types/react-query';
import { formatDate, formatDuration, formatNumber } from '@/lib/format';
import { GROUP_LABELS, GROUP_ORDER, isActive } from '@/lib/collection/labels';
import { useStartCollection } from '@/lib/collection/useStartCollection';
import styles from './collection.module.css';

/** Pendências de coleta no painel (PRD §8.1, ADR-07): o que falta e o botão para coletar. */
export default function CollectionPendingCard() {
  const router = useRouter();
  const { data, isError, isPending } = useQuery({
    ...getCollectionPendingOptions(),
    refetchInterval: (query) => (isActive(query.state.data?.active_run) ? 30_000 : 60_000),
  });
  const { start, isStarting, errorMessage } = useStartCollection(() => router.push('/app/coleta'));

  return (
    <section className={`${styles.card} ${styles.wide}`} aria-labelledby="pending-title" aria-busy={isPending}>
      <h2 id="pending-title" className={`${styles.eyebrow} mono`}>
        Pendências de coleta
      </h2>
      {isError && !data && (
        <p className={styles.muted}>Não foi possível consultar as pendências. O engine está no ar?</p>
      )}
      {data && <PendingBody data={data} onStart={start} isStarting={isStarting} />}
      {errorMessage && (
        <p className={styles.error} role="alert">
          {errorMessage}
        </p>
      )}
    </section>
  );
}

function PendingBody({ data, onStart, isStarting }: { data: CollectionPendingResponse; onStart: () => void; isStarting: boolean }) {
  const counts = new Map(data.counts.map((c) => [c.group, c.count]));
  const days = data.pending_days;
  const nothingKnown = data.known_requests === 0 && data.days_awaiting_cotahist === 0;
  const active = data.active_run;

  return (
    <>
      <p className={styles.headline}>
        {nothingKnown
          ? `Tudo coletado até ${formatDate(data.reference_date)}.`
          : `${formatNumber(days.length)} pregão(ões) com pendência, até ${formatDate(data.reference_date)}.`}
      </p>
      {data.data_source === 'fixtures' && (
        <p className={styles.row}>
          <span className={styles.badge}>Fonte simulada</span>
          <span className={styles.muted}>O engine lê arquivos salvos; nada é baixado da B3.</span>
        </p>
      )}
      {data.is_initial_load && !nothingKnown && (
        <p className={`${styles.muted} ${styles.row}`}>
          Carga inicial: começa pelos COTAHIST e pelo ativo-objeto e pode ser feita em várias sessões. Se o
          computador desligar, a coleta continua de onde parou.
        </p>
      )}
      {!nothingKnown && (
        <dl className={styles.counts}>
          {GROUP_ORDER.filter((g) => (counts.get(g) ?? 0) > 0).map((g) => (
            <div key={g}>
              <dt>{GROUP_LABELS[g]}</dt>
              <dd className="mono">{formatNumber(counts.get(g))}</dd>
            </div>
          ))}
          {data.days_awaiting_cotahist > 0 && (
            <div>
              <dt>Opções a definir (após o COTAHIST)</dt>
              <dd className="mono">{formatNumber(data.days_awaiting_cotahist)} pregão(ões)</dd>
            </div>
          )}
          <div>
            <dt>Tempo estimado (requisições conhecidas)</dt>
            <dd className="mono">{formatDuration(data.estimated_seconds)}</dd>
          </div>
        </dl>
      )}
      <div className={styles.row}>
        {active ? (
          <>
            <span className={styles.status} data-tone="ok">
              <span className={styles.dot} aria-hidden="true" />
              Coleta em andamento
            </span>
            <Link href="/app/coleta" className={styles.link}>
              Acompanhar
            </Link>
          </>
        ) : (
          !nothingKnown && (
            <button type="button" className={styles.button} onClick={onStart} disabled={isStarting}>
              {isStarting ? 'Iniciando…' : 'Coletar agora'}
            </button>
          )
        )}
        {!active && (
          <Link href="/app/coleta" className={styles.link}>
            Última coleta e relatório de lacunas
          </Link>
        )}
      </div>
    </>
  );
}
