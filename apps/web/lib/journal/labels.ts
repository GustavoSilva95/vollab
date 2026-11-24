import type { EntryOut, LimitOut, MarkLegOut, PositionSummary, ScenarioOut } from '@vollab/api-types';

/**
 * Textos do diário, da carteira e do risco (PRD 1.10 §5.9 e §8.1; BRD 1.7 RF-DIA-02..04, RF-RSK-01..04).
 */

export const ENTRY_KIND_LABEL: Record<EntryOut['kind'], string> = {
  entry: 'Entrada',
  hedge: 'Hedge',
  strike_adjustment: 'Ajuste de strike',
  exercise: 'Exercício',
  assignment: 'Designação',
  exit: 'Saída',
  roll: 'Rolagem',
  void: 'Estorno',
};

export const STATUS_LABEL: Record<PositionSummary['status'], string> = { open: 'Aberta', closed: 'Encerrada' };

export const MARK_ORIGIN_LABEL: Record<MarkLegOut['origin'], string> = {
  observed: 'IV de referência',
  approximate: 'aproximado',
  stale: 'desatualizado',
  expired: 'vencida',
};

export const MARK_ORIGIN_HELP: Record<MarkLegOut['origin'], string> = {
  observed: 'Preço por Black-Scholes com a IV de referência da série no pregão (QA-04).',
  approximate: 'Sem IV de referência: fechamento oficial do COTAHIST, com a IV extraída dele (fechamentos não sincronizados).',
  stale: 'Sem IV nem fechamento no pregão: repete a IV da marcação anterior, com o preço do ativo do dia.',
  expired: 'No vencimento e depois dele vale o valor intrínseco do pregão do vencimento.',
};

export const RESIDUAL_HELP =
  'Resíduo = P&L de mercado − (delta + gamma + theta + vega): termos de ordem mais alta, mudança da taxa, ou erro de lançamento. Sempre exibido (RF-DIA-04).';

export const EXECUTION_HELP =
  'Execução e custos: diferença entre o preço executado e a marcação do dia, menos taxas e corretagem. Fica fora do resíduo.';

export const CS04_HELP =
  'CS-04: Σ|resíduo| ÷ Σ(|delta| + |gamma| + |theta| + |vega|) ao longo da vida da operação, fora execução e custos.';

export const ERROR_FLAG_HELP =
  'Dia com resíduo acima de 15% da soma dos módulos dos Greeks e acima do mínimo em R$ (não calibrado): confira os lançamentos (RS-06).';

export const DELTA_BAND_HELP =
  'Delta da última marcação contra a banda da simulação (não calibrada). É um indicador; o alerta persistente vem na Etapa 8.';

export const LIMIT_LABEL: Record<LimitOut['name'], string> = {
  stress_loss: 'Pior perda em stress ÷ capital',
  vega_total: '|Vega| da carteira por ponto ÷ capital',
  underlying_concentration: 'Perda em stress do ativo ÷ orçamento de perda',
  expiry_concentration: 'Perda em stress do vencimento ÷ orçamento de perda',
};

export const LIMIT_STATE_LABEL: Record<LimitOut['state'], string> = {
  ok: 'Dentro',
  breached: 'Ultrapassado',
  unavailable: 'Indisponível',
};

export const SCENARIO_ORIGIN_LABEL: Record<ScenarioOut['origin'], string> = {
  estimated: 'estimado',
  approximate: 'aproximado',
  manual: 'manual',
};

export const CRISIS_HELP =
  'Choques medidos nos COTAHIST de 2017 e 2020 (QA-12): pior retorno em 5 pregões no episódio e alta da IV ATM dos fechamentos das opções (aproximada; sem opções líquidas, alta da RV de 20 pregões).';
