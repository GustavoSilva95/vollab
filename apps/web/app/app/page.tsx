import type { Metadata } from 'next';
import EngineStatus from '@/components/cockpit/EngineStatus';
import styles from './page.module.css';

export const metadata: Metadata = { title: 'Painel' };

const UPCOMING = [
  { title: 'Pendências de coleta', text: 'Pregões ainda não coletados e botão para coletar.', stage: 2 },
  { title: 'Alertas', text: 'Hedge, saída, rolagem, limites e proventos com posição aberta.', stage: 8 },
  { title: 'Resumo da carteira', text: 'Greeks agregados e exposição por vencimento.', stage: 7 },
];

/** Painel (PRD §8.1). Na Etapa 1 mostra só o estado do engine. */
export default function DashboardPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Painel</h1>
        <p className={styles.subtitle}>Situação do engine, pendências de coleta e alertas.</p>
      </header>

      <div className={styles.grid}>
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
