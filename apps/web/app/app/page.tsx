import type { Metadata } from 'next';
import EngineStatus from '@/components/cockpit/EngineStatus';
import CollectionPendingCard from '@/components/cockpit/collection/CollectionPendingCard';
import AlertsCard from '@/components/cockpit/alerts/AlertsCard';
import styles from './page.module.css';

export const metadata: Metadata = { title: 'Painel' };

const UPCOMING = [{ title: 'Resumo da carteira', text: 'Greeks agregados e exposição por vencimento.', stage: 7 }];

/** Painel (PRD §8.1): estado do engine, pendências de coleta (Etapa 2) e alertas (Etapa 8, PRD-UI-10). */
export default function DashboardPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Painel</h1>
        <p className={styles.subtitle}>Situação do engine, pendências de coleta e alertas.</p>
      </header>

      <div className={styles.grid}>
        <AlertsCard />
        <CollectionPendingCard />
        <EngineStatus />
        {UPCOMING.map((item) => (
          <section key={item.title} className={styles.placeholder} aria-label={item.title}>
            <h2 className={styles.placeholderTitle}>{item.title}</h2>
            <p className={styles.placeholderText}>{item.text}</p>
            <p className={`${styles.stage} mono`}>Etapa {item.stage}</p>
          </section>
        ))}
      </div>
    </>
  );
}
