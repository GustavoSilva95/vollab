import type { Metadata } from 'next';
import SimulatorView from '@/components/cockpit/simulator/SimulatorView';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Simulador' };

const TICKER = /^[A-Z0-9]{4,12}$/;

/**
 * Simulador e dimensionamento (PRD 1.9 §8.1; RF-SIM-01..05, RN-SIZ-01..06): casca no servidor; a
 * simulação no cliente, recalculada pelo engine a cada pedido. Aberta com `?ticker=` a partir do
 * ranking e da tela do ativo.
 */
export default async function SimulatorPage({ searchParams }: PageProps<'/app/simulador'>) {
  const raw = (await searchParams).ticker;
  const ticker = typeof raw === 'string' && TICKER.test(raw.toUpperCase()) ? raw.toUpperCase() : null;
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Simulador</h1>
        <p className={styles.subtitle}>
          Monte a estrutura com séries reais, veja o edge e o semáforo da estrutura, a distribuição simulada do P&amp;L e
          o tamanho pelo Kelly fracionado e pelo teto de perda. Nada é gravado até registrar a entrada.
        </p>
      </header>
      <SimulatorView initialTicker={ticker} />
    </>
  );
}
