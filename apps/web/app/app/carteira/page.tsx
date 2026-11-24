import type { Metadata } from 'next';
import PortfolioView from '@/components/cockpit/portfolio/PortfolioView';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Carteira' };

/** Carteira e risco (PRD 1.10 §8.1; RF-RSK-01..04): casca no servidor; cálculo na leitura pelo engine. */
export default function PortfolioPage() {
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Carteira</h1>
        <p className={styles.subtitle}>
          Greeks agregados e por ativo, exposição por vencimento, stresses (inclusive os cenários de crise) e limites, a partir
          da marcação D-1 das operações abertas.
        </p>
      </header>
      <PortfolioView />
    </>
  );
}
