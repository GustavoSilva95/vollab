import type { Metadata } from 'next';
import RankingView from '@/components/cockpit/ranking/RankingView';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Ranking' };

/**
 * Ranking de oportunidades (PRD 1.8 §8.1; RF-RNK-01/02): casca no servidor; a tabela no cliente, com
 * o que o engine calcula na leitura.
 */
export default function RankingPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Ranking</h1>
        <p className={styles.subtitle}>
          Ativos cadastrados ordenados pelo semáforo e pelo edge relativo líquido: prêmio de vol descontado do spread normal,
          com intervalo, contra custos estimados e o limiar.
        </p>
      </header>
      <RankingView />
    </>
  );
}
