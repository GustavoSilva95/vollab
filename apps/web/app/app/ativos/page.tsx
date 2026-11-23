import type { Metadata } from 'next';
import UnderlyingList from '@/components/cockpit/vol/UnderlyingList';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Ativos' };

/** Ativos cadastrados: entrada para a tela de cada ativo (PRD §8.1, `/app/ativos/[ticker]`). */
export default function AssetsPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Ativos</h1>
        <p className={styles.subtitle}>
          Volatilidade realizada pelos estimadores do livro-base, IV, smile, estrutura a termo e salto de eventos.
        </p>
      </header>
      <UnderlyingList />
    </>
  );
}
