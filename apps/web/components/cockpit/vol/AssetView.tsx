'use client';

import ImpliedPanel from './ImpliedPanel';
import RealizedPanel from './RealizedPanel';
import { AssetSummary, EventJumpsCard, SeriesCard } from './AssetDetails';
import styles from './vol.module.css';

/** Tela do ativo (PRD §8.1): RV lado a lado, IV, smile, estrutura a termo, eventos e salto. */
export default function AssetView({ ticker }: { ticker: string }) {
  return (
    <div className={styles.grid}>
      <AssetSummary ticker={ticker} />
      <RealizedPanel ticker={ticker} />
      <ImpliedPanel ticker={ticker} />
      <EventJumpsCard ticker={ticker} />
      <SeriesCard ticker={ticker} />
    </div>
  );
}
