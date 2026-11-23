import type { Metadata } from 'next';
import ModelsView from '@/components/cockpit/models/ModelsView';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Modelos' };

/**
 * Modelos de previsão de RV (PRD 1.7 §8.1; RF-PRV-01..04, CS-03): casca no servidor; tabelas e gráfico
 * no cliente, com o que o worker já calculou.
 */
export default function ModelsPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Modelos</h1>
        <p className={styles.subtitle}>
          Previsão de volatilidade realizada por modelo, erro contra os baselines em janelas não sobrepostas e o modelo
          usado no edge.
        </p>
      </header>
      <ModelsView />
    </>
  );
}
