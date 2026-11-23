import type { EstimatedValue } from '@vollab/api-types';
import { formatVol } from '@/lib/format';
import { ORIGIN_HELP, ORIGIN_LABEL } from '@/lib/vol/labels';
import styles from './vol.module.css';

interface Props {
  value: EstimatedValue | null | undefined;
  /** Formatação da unidade (padrão: vol decimal → %). */
  format?: (v: number) => string;
  /** Mostra o intervalo quando existir. */
  showInterval?: boolean;
}

/**
 * Valor com proveniência (PRD §5.2). Nunca mostra número quando o status não é `ok`
 * (PRD-UI-08) e rotula toda origem diferente de "observado" (PRD-UI-02).
 */
export default function EstimatedValueView({ value, format = formatVol, showInterval = false }: Props) {
  if (!value) return <span className={styles.muted}>—</span>;
  if (value.status !== 'ok' || value.value == null) {
    const label = value.status === 'insufficient_data' ? 'dados insuficientes' : 'indisponível';
    return (
      <span className={styles.state} title={value.reason ?? undefined} data-status={value.status}>
        {label}
        {value.reason && <span className="sr-only">: {value.reason}</span>}
      </span>
    );
  }
  const hasInterval = showInterval && value.ci_low != null && value.ci_high != null;
  return (
    <span>
      <span className={styles.value}>{format(value.value)}</span>
      {hasInterval && (
        <span className={`${styles.muted} ${styles.small}`}>
          {' '}
          [{format(value.ci_low as number)} – {format(value.ci_high as number)}]
        </span>
      )}
      {value.origin !== 'observed' && (
        <span className={styles.tag} title={ORIGIN_HELP[value.origin]}>
          {ORIGIN_LABEL[value.origin]}
        </span>
      )}
      {value.stale && (
        <span className={styles.tag} title="Dado mais antigo que o último pregão.">
          desatualizado
        </span>
      )}
      {value.reason && (
        <span className={`${styles.muted} ${styles.small}`} title={value.reason}>
          {' '}
          ⓘ<span className="sr-only">{value.reason}</span>
        </span>
      )}
    </span>
  );
}
