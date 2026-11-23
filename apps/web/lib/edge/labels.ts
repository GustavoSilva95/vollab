import type { RankingRow } from '@vollab/api-types';

/**
 * Semáforo de edge (BRD 1.5 RN-EDG-03, PRD 1.8 §5.6.1). Estado sempre com texto, além da cor
 * (acessibilidade): a cor nunca é a única pista.
 */
export type EdgeState = RankingRow['state'];
export type Direction = NonNullable<RankingRow['direction']>;

export const STATE_LABEL: Record<EdgeState, string> = {
  edge: 'Edge líquido',
  inconclusive: 'Inconclusivo',
  no_edge: 'Sem edge',
  unavailable: 'Indisponível',
};

export const STATE_HELP: Record<EdgeState, string> = {
  edge: 'O intervalo inteiro do prêmio passa dos custos mais o limiar nesta direção.',
  inconclusive: 'O intervalo do prêmio contém o nível exigido: a amostra não decide.',
  no_edge: 'Nenhuma direção paga os custos mais o limiar, nem no extremo do intervalo.',
  unavailable: 'Falta um insumo (IV, previsão avaliada ou custos); veja o motivo.',
};

export const DIRECTION_LABEL: Record<Direction, string> = {
  sell: 'vender vol',
  buy: 'comprar vol',
};

/** Rótulo do estado com a direção quando houver edge líquido. */
export function stateText(row: Pick<RankingRow, 'state' | 'direction'>): string {
  if (row.state === 'edge' && row.direction) return `${STATE_LABEL.edge} (${DIRECTION_LABEL[row.direction]})`;
  return STATE_LABEL[row.state];
}

export const NOT_CALIBRATED_HELP =
  'Valor configurado, ainda sem calibração por dados. O spread normal calibra com ≥ 8 janelas de IV de prazo constante (QA-14); o limiar, com operações registradas (Etapa 9).';

export const SPREAD_ESTIMATE_HELP =
  'Estimativa pela dispersão dos negócios do dia (mediana de |Δpreço| entre negócios consecutivos), com piso de um tick. O spread de fechamento do COTAHIST aparece só como conferência.';
