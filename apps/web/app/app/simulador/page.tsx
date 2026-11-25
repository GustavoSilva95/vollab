import type { Metadata } from 'next';
import SimulatorView from '@/components/cockpit/simulator/SimulatorView';
import { STRUCTURES } from '@/lib/simulator/labels';
import styles from '../page.module.css';

export const metadata: Metadata = { title: 'Simulador' };

const TICKER = /^[A-Z0-9]{4,12}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ID = /^[1-9]\d{0,9}$/;

/**
 * Simulador e dimensionamento (PRD 1.9 §8.1; RF-SIM-01..05, RN-SIZ-01..06): casca no servidor; a
 * simulação no cliente, recalculada pelo engine a cada pedido. Aberta com `?ticker=` a partir do
 * ranking e da tela do ativo.
 */
export default async function SimulatorPage({ searchParams }: PageProps<'/app/simulador'>) {
  const params = await searchParams;
  const raw = params.ticker;
  const ticker = typeof raw === 'string' && TICKER.test(raw.toUpperCase()) ? raw.toUpperCase() : null;
  // Modo rolagem (PRD 1.11 §5.10, RN-GES-04): aberto pela sugestão do alerta ou da operação.
  const rollFrom = typeof params.roll_from === 'string' && ID.test(params.roll_from) ? Number(params.roll_from) : null;
  const expiry = typeof params.expiry === 'string' && ISO_DATE.test(params.expiry) ? params.expiry : null;
  const structure = STRUCTURES.find((s) => s.name === params.structure)?.name ?? null;
  const roll = rollFrom != null ? { positionId: rollFrom, expiry, structure } : null;
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Simulador</h1>
        <p className={styles.subtitle}>
          Monte a estrutura com séries reais, veja o edge e o semáforo da estrutura, a distribuição simulada do P&amp;L e
          o tamanho pelo Kelly fracionado e pelo teto de perda. Nada é gravado até registrar a entrada.
        </p>
      </header>
      <SimulatorView initialTicker={ticker} roll={roll} />
    </>
  );
}
