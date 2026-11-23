import type { EstimatorSeries, EventOut } from '@vollab/api-types';

export type EstimatorName = EstimatorSeries['estimator'];
export type EventKind = EventOut['kind'];

/**
 * Estimadores de RV (RF-VOL-01) e a hipótese de cada um (RN-VOL-09, PRD §5.5). A interface sempre
 * mostra a hipótese: os de range supõem drift zero e sem gap e tendem a subestimar com gap noturno.
 */
export const ESTIMATORS: readonly { name: EstimatorName; label: string; hypothesis: string }[] = [
  {
    name: 'close_to_close',
    label: 'Close-to-close (média zero)',
    hypothesis: 'Só fechamentos; média zero e divisor n (padrão). Inclui o gap da noite; converge devagar.',
  },
  {
    name: 'close_to_close_demeaned',
    label: 'Close-to-close (média subtraída)',
    hypothesis: 'Só fechamentos; média subtraída e divisor n − 1. Exibido para comparação.',
  },
  {
    name: 'parkinson',
    label: 'Parkinson',
    hypothesis: 'Máxima e mínima. Supõe drift zero e sem gap de abertura: subestima com gap noturno.',
  },
  {
    name: 'garman_klass',
    label: 'Garman-Klass',
    hypothesis: 'OHLC do pregão. Supõe drift zero e sem gap de abertura: subestima com gap noturno.',
  },
  {
    name: 'rogers_satchell',
    label: 'Rogers-Satchell',
    hypothesis: 'OHLC do pregão. Aceita drift; ignora a noite.',
  },
  {
    name: 'yang_zhang',
    label: 'Yang-Zhang',
    hypothesis: 'Noite + pregão + Rogers-Satchell. Aceita drift e gap de abertura.',
  },
  {
    name: 'intraday_5m',
    label: 'Intradiária (5 min)',
    hypothesis:
      'Barras de 5 min da sessão regular + retorno da noite. Pregão com menos de 80% das barras com negócio fica fora.',
  },
];

export const ESTIMATOR_LABEL: Record<EstimatorName, string> = Object.fromEntries(
  ESTIMATORS.map((e) => [e.name, e.label]),
) as Record<EstimatorName, string>;

export const EVENT_KIND_LABEL: Record<EventKind, string> = {
  earnings: 'Resultado',
  ex_dividend: 'Ex-dividendo',
  ex_jcp: 'Ex-JCP',
  copom: 'Copom',
  macro: 'Macro',
  expiry: 'Vencimento',
};

export const EDITABLE_EVENT_KINDS = ['earnings', 'ex_dividend', 'ex_jcp', 'copom', 'macro'] as const;

export const ORIGIN_LABEL = {
  observed: 'observado',
  estimated: 'estimado',
  manual: 'manual',
  approximate: 'aproximado',
} as const;

export const ORIGIN_HELP = {
  observed: 'Dado observado na fonte oficial.',
  estimated: 'Valor estimado pelo engine a partir dos dados coletados.',
  manual: 'Valor informado manualmente.',
  approximate: 'Aproximação: método alternativo usado por falta do principal.',
} as const;
