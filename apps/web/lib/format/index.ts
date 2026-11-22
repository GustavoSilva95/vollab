/**
 * Módulo ÚNICO de formatação de unidades (PRD-UI-03, PRD §5.1, RN-PRC-04).
 *
 * Regras:
 * - A API e o banco trafegam vol em decimal anualizado (base 252), taxa em decimal
 *   exponencial e dinheiro em decimal exato (string). **Percentual só existe aqui.**
 * - Nenhuma função aceita percentual como entrada nem devolve número: todas devolvem
 *   texto para exibição. Conversões de cálculo (anos úteis, anualização) são do engine.
 * - Valor ausente (`null`/`undefined`) vira `EMPTY`. Estados "dados insuficientes" e
 *   "indisponível" são componentes próprios (PRD-UI-08), não um número.
 * - Componentes não formatam número por conta própria: o ESLint bloqueia `toFixed`,
 *   `toLocaleString` e `Intl.*Format` fora desta pasta.
 */

export const LOCALE = 'pt-BR';
export const MARKET_TIME_ZONE = 'America/Sao_Paulo';
export const EMPTY = '—';

/**
 * Teto de sanidade para vol decimal: 5 = 500% a.a. Um valor acima disso quase certamente
 * é um percentual passado por engano (ex.: 25.34 em vez de 0.2534) e é rejeitado.
 */
export const MAX_DECIMAL_VOL = 5;
/** Teto de sanidade para prêmio de vol em decimal: 1 = 100 pontos de vol. */
export const MAX_DECIMAL_VOL_PREMIUM = 1;
/** Teto de sanidade para taxa de juros decimal: 1 = 100% a.a. */
export const MAX_DECIMAL_RATE = 1;

type Maybe<T> = T | null | undefined;

const numberFormatCache = new Map<string, Intl.NumberFormat>();

function numberFormat(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(options);
  let format = numberFormatCache.get(key);
  if (!format) {
    // signDisplay 'negative': -0 e arredondamentos para zero não exibem "-0,00".
    format = new Intl.NumberFormat(LOCALE, { signDisplay: 'negative', ...options });
    numberFormatCache.set(key, format);
  }
  return format;
}

function assertFinite(value: number, what: string): void {
  if (!Number.isFinite(value)) {
    throw new RangeError(`${what}: valor não finito (${String(value)}).`);
  }
}

function assertDecimalScale(value: number, max: number, what: string): void {
  assertFinite(value, what);
  if (Math.abs(value) > max) {
    throw new RangeError(
      `${what}: ${String(value)} está fora da escala decimal. A API usa decimal (0.2534 = 25,34%), nunca percentual.`,
    );
  }
}

function fixed(decimals: number): Intl.NumberFormatOptions {
  return { minimumFractionDigits: decimals, maximumFractionDigits: decimals };
}

/** Volatilidade decimal anualizada (base 252) → `25,34%`. */
export function formatVol(vol: Maybe<number>, decimals = 2): string {
  if (vol == null) return EMPTY;
  assertDecimalScale(vol, MAX_DECIMAL_VOL, 'formatVol');
  return numberFormat({ style: 'percent', ...fixed(decimals) }).format(vol);
}

/** Prêmio de vol em decimal (pontos de vol / 100) → `3,1 pts`. 1 ponto = 0,01. */
export function formatVolPoints(premium: Maybe<number>, decimals = 1): string {
  if (premium == null) return EMPTY;
  assertDecimalScale(premium, MAX_DECIMAL_VOL_PREMIUM, 'formatVolPoints');
  return `${numberFormat(fixed(decimals)).format(premium * 100)} pts`;
}

/** Taxa decimal anual, capitalização exponencial, base 252 → `13,65% a.a.`. */
export function formatRate(rate: Maybe<number>, decimals = 2): string {
  if (rate == null) return EMPTY;
  assertDecimalScale(rate, MAX_DECIMAL_RATE, 'formatRate');
  return `${numberFormat({ style: 'percent', ...fixed(decimals) }).format(rate)} a.a.`;
}

function formatDays(days: Maybe<number>, suffix: string, what: string): string {
  if (days == null) return EMPTY;
  assertFinite(days, what);
  if (!Number.isInteger(days)) {
    throw new RangeError(`${what}: dias devem ser inteiros (${String(days)}).`);
  }
  return `${numberFormat({ maximumFractionDigits: 0 }).format(days)} ${suffix}`;
}

/** Dias úteis (campos `_bd`) → `21 du`. */
export function formatBusinessDays(days: Maybe<number>): string {
  return formatDays(days, 'du', 'formatBusinessDays');
}

/** Dias corridos (campos `_cd`) → `30 dc`. */
export function formatCalendarDays(days: Maybe<number>): string {
  return formatDays(days, 'dc', 'formatCalendarDays');
}

const DECIMAL_STRING = /^-?\d+(\.\d+)?$/;

/**
 * Dinheiro em BRL → `R$ 1.234,56`. Aceita a string decimal exata que a API envia
 * (Decimal/NUMERIC), sem passar por float.
 */
export function formatMoney(value: Maybe<string | number>, decimals = 2): string {
  if (value == null) return EMPTY;
  if (typeof value === 'string') {
    if (!DECIMAL_STRING.test(value)) {
      throw new RangeError(`formatMoney: "${value}" não é um decimal válido.`);
    }
    return numberFormat({ style: 'currency', currency: 'BRL', ...fixed(decimals) }).format(
      value as Intl.StringNumericLiteral,
    );
  }
  assertFinite(value, 'formatMoney');
  return numberFormat({ style: 'currency', currency: 'BRL', ...fixed(decimals) }).format(value);
}

/** Número genérico (contagens, quantidades) → `1.234` ou `1.234,5`. */
export function formatNumber(value: Maybe<number>, maxDecimals = 0): string {
  if (value == null) return EMPTY;
  assertFinite(value, 'formatNumber');
  return numberFormat({ maximumFractionDigits: maxDecimals }).format(value);
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Data de pregão (`date`, `YYYY-MM-DD`) → `22/11/2026`. Não passa por `Date`:
 * uma data sem hora não pode "andar" um dia por causa de fuso.
 */
export function formatDate(isoDate: Maybe<string>): string {
  if (isoDate == null) return EMPTY;
  const match = ISO_DATE.exec(isoDate);
  if (!match) throw new RangeError(`formatDate: "${isoDate}" não está no formato AAAA-MM-DD.`);
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}

const dateTimeFormat = new Intl.DateTimeFormat(LOCALE, {
  timeZone: MARKET_TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

/** Instante (`timestamptz` em ISO 8601) → `22/11/2026 14:35:02`, sempre no horário de Brasília. */
export function formatDateTime(isoDateTime: Maybe<string>): string {
  if (isoDateTime == null) return EMPTY;
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) {
    throw new RangeError(`formatDateTime: "${isoDateTime}" não é uma data/hora válida.`);
  }
  return dateTimeFormat.format(date).replace(', ', ' ');
}

/**
 * Duração estimada em segundos → `≈ 5 h 02 min`, `12 min`, `45 s`. Para estimativas de
 * tempo (coleta), arredonda para minutos acima de 1 minuto.
 */
export function formatDuration(seconds: Maybe<number>): string {
  if (seconds == null) return EMPTY;
  assertFinite(seconds, 'formatDuration');
  if (seconds < 0) throw new RangeError(`formatDuration: duração negativa (${String(seconds)}).`);
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const minutes = Math.round(total / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${numberFormat({ maximumFractionDigits: 0 }).format(hours)} h ${String(rest).padStart(2, '0')} min`;
}

/** Parte de um total → `40%` (progresso). Total zero → `EMPTY`. */
export function formatShare(part: Maybe<number>, total: Maybe<number>): string {
  if (part == null || total == null || total === 0) return EMPTY;
  assertFinite(part, 'formatShare');
  assertFinite(total, 'formatShare');
  if (part < 0 || part > total) throw new RangeError(`formatShare: ${String(part)} fora de 0..${String(total)}.`);
  return numberFormat({ style: 'percent', maximumFractionDigits: 0 }).format(part / total);
}
