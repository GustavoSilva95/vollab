import type { RankingRow } from '@vollab/api-types';
import { STATE_HELP, stateText } from '@/lib/edge/labels';
import local from '../ranking/ranking.module.css';

/**
 * Selo do semáforo (RN-EDG-03): estado com texto e cor, nunca só a cor. Módulo leve, compartilhado
 * pelo ranking e pelo simulador (revisão de performance da Etapa 6, I-2: o simulador não carrega a
 * tabela do ranking).
 */
export default function StateBadge({ row }: { row: Pick<RankingRow, 'state' | 'direction' | 'reason'> }) {
  return (
    <span className={local.badge} data-state={row.state} title={row.reason ?? STATE_HELP[row.state]}>
      {stateText(row)}
    </span>
  );
}
