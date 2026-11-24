import type { Metadata } from 'next';
import JournalList from '@/components/cockpit/journal/JournalList';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Diário' };

/** Diário (PRD 1.10 §8.1; RF-DIA-01..04): casca no servidor; a lista no cliente. */
export default function JournalPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Diário</h1>
        <p className={styles.subtitle}>
          Operações registradas, com o status que vem dos lançamentos, o P&amp;L até a última marcação D-1 e o resíduo da
          atribuição (CS-04).
        </p>
      </header>
      <JournalList />
    </>
  );
}
