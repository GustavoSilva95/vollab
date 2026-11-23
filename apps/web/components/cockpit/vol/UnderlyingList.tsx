'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { listUnderlyingsOptions } from '@vollab/api-types/react-query';
import styles from './vol.module.css';

/** Ativos cadastrados (BRD §5.1), com link para a tela de cada um. */
export default function UnderlyingList() {
  const { data, isError, isPending } = useQuery(listUnderlyingsOptions());
  return (
    <section className={styles.card} aria-labelledby="assets-title" aria-busy={isPending}>
      <h2 id="assets-title" className={`${styles.eyebrow} mono`}>
        Cadastrados
      </h2>
      {isError && <p className={styles.error}>Não foi possível listar os ativos. O engine está no ar?</p>}
      {data && data.length === 0 && <p className={styles.muted}>Nenhum ativo cadastrado.</p>}
      {data && data.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 8 }}>
          {data.map((u) => (
            <li key={u.ticker}>
              <Link className={styles.link} href={`/app/ativos/${u.ticker}`}>
                {u.ticker}
              </Link>{' '}
              {!u.active && <span className={styles.tag}>inativo</span>}
              {u.isin == null && <span className={`${styles.muted} ${styles.small}`}> ISIN após a próxima coleta</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
