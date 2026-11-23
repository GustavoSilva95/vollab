import type { EvaluationRow } from '@vollab/api-types';

export type EvaluatedName = EvaluationRow['model'];

/**
 * Modelos de previsão e baselines (RF-PRV-02/03, PRD 1.7 §5.7), com a hipótese de cada um. A interface
 * sempre explica o que o número supõe.
 */
export const FORECAST_MODELS: readonly { name: EvaluatedName; label: string; help: string }[] = [
  {
    name: 'ewma',
    label: 'EWMA',
    help: 'Média exponencial dos retornos ao quadrado (λ configurável, padrão 0,94). Previsão plana: ignora a reversão à média.',
  },
  {
    name: 'combination',
    label: 'Combinação de estimadores',
    help: 'Média simples das variâncias de 20 pregões: close-to-close, Yang-Zhang, Rogers-Satchell e intradiária (quando houver). Parkinson e Garman-Klass ficam fora por suporem que não há gap.',
  },
  {
    name: 'garch',
    label: 'GARCH(1,1)',
    help: 'Variância condicional com reversão à média (eqs. 4.4–4.9). Instável com pouco histórico: a referência recomenda ≥ 1.000 retornos.',
  },
  {
    name: 'rv_c2c_20',
    label: 'Baseline: RV close-to-close 20 du',
    help: 'Usa a RV dos últimos 20 pregões como previsão. Não alimenta o edge.',
  },
  {
    name: 'implied',
    label: 'Baseline: IV de prazo constante',
    help: 'A previsão do mercado (com eventos). Só no prazo constante configurado. Não alimenta o edge.',
  },
];

export const MODEL_LABEL: Record<EvaluatedName, string> = Object.fromEntries(
  FORECAST_MODELS.map((m) => [m.name, m.label]),
) as Record<EvaluatedName, string>;

export const MODEL_HELP: Record<EvaluatedName, string> = Object.fromEntries(
  FORECAST_MODELS.map((m) => [m.name, m.help]),
) as Record<EvaluatedName, string>;
