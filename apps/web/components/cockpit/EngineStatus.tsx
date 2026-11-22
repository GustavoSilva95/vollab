'use client';

import { useQuery } from '@tanstack/react-query';
import { getHealthOptions } from '@vollab/api-types/react-query';
import { formatDateTime } from '@/lib/format';
import styles from './EngineStatus.module.css';

type Tone = 'ok' | 'warn' | 'danger' | 'muted';

/** Estado do engine e do banco (GET /health), atualizado a cada 30 s. */
export default function EngineStatus() {
  const { data, isPending, isError } = useQuery({ ...getHealthOptions(), refetchInterval: 30_000 });

  let tone: Tone = 'muted';
  let label = 'Verificando…';
  if (isError) {
    tone = 'danger';
    label = 'Engine offline';
  } else if (data) {
    tone = data.status === 'ok' ? 'ok' : 'warn';
    label = data.status === 'ok' ? 'Engine online' : 'Engine sem banco de dados';
  }

  return (
    <section className={styles.card} aria-labelledby="engine-status-title" aria-busy={isPending}>
      <h2 id="engine-status-title" className={`${styles.title} mono`}>
        Engine
      </h2>
      <p className={styles.status} data-tone={tone} role="status">
        <span className={styles.dot} aria-hidden="true" />
        {label}
      </p>
      {isError && (
        <p className={styles.hint}>
          Suba o engine com <code className="mono">npm run engine:up</code> e recarregue a página.
        </p>
      )}
      {data && (
        <dl className={styles.details}>
          <div>
            <dt>Banco de dados</dt>
            <dd>{data.database === 'ok' ? 'conectado' : 'indisponível'}</dd>
          </div>
          <div>
            <dt>Versão</dt>
            <dd className="mono">{data.engine_version}</dd>
          </div>
          <div>
            <dt>Última coleta</dt>
            <dd>{data.last_collection_at ? formatDateTime(data.last_collection_at) : 'nenhuma ainda'}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
