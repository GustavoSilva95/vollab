import type { Metadata } from 'next';
import CollectionMonitor from '@/components/cockpit/collection/CollectionMonitor';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Coleta' };

/** Coleta (PRD §8.1): execução, progresso e relatório de lacunas. Dados via TanStack Query. */
export default function CollectionPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Coleta</h1>
        <p className={styles.subtitle}>
          Dados oficiais da B3 (COTAHIST e negócios), Selic e proventos. A coleta roda no worker do engine e continua de
          onde parou se for interrompida.
        </p>
      </header>
      <CollectionMonitor />
    </>
  );
}
