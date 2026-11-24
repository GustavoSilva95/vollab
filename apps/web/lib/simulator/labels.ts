import type { SimulationResponse, SizingOut } from '@vollab/api-types';

/**
 * Estruturas do simulador (BRD 1.6 RF-SIM-01) e textos da tela (PRD 1.9 §5.8, PRD-UI-09).
 */
export type StructureName = SimulationResponse['structure'];

export const STRUCTURES: readonly { name: StructureName; label: string; legs: 'call' | 'call_put' }[] = [
  { name: 'short_straddle', label: 'Straddle vendido', legs: 'call_put' },
  { name: 'short_strangle', label: 'Strangle vendido', legs: 'call_put' },
  { name: 'covered_call', label: 'Venda coberta', legs: 'call' },
  { name: 'long_straddle', label: 'Straddle comprado', legs: 'call_put' },
  { name: 'long_strangle', label: 'Strangle comprado', legs: 'call_put' },
];

export const STRUCTURE_LABEL = Object.fromEntries(STRUCTURES.map((s) => [s.name, s.label])) as Record<
  StructureName,
  string
>;

export const RULE_LABEL: Record<SizingOut['rule'], string> = {
  kelly: 'Prevaleceu o Kelly fracionado',
  cap: 'Prevaleceu o teto de perda',
  tie: 'Kelly e teto empatados',
  zero: 'Sem tamanho sugerido',
};

export const STRESS_LABEL: Record<string, string> = {
  gap_down: 'Gap de queda',
  gap_up: 'Gap de alta',
  vol_up: 'Alta de vol',
  down_vol_up: 'Queda com alta de vol',
};

export const DELTA_BAND_HELP =
  'Hedge por banda de delta (QA-11): fora da banda, ajusta só até a borda, à IV de entrada. Largura configurada, ainda sem calibração por dados.';

export const IV_CONSTANT_HELP =
  'A IV de cada perna fica constante na simulação; o risco de vega aparece só no stress (alta de vol).';

export const DISTRIBUTION_HELP =
  'Bootstrap dos retornos diários reais do último ano (com os gaps), com média zero e reescalados para a RV prevista (QA-10).';

export const KAMAL_DERMAN_HELP =
  'Desvio do P&L por hedge discreto diário pela eq. 7.7 (Kamal-Derman): aproximação, só para comparar a ordem de grandeza.';
