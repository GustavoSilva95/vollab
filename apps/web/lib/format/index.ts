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

/** Fração decimal (cobertura, participação) → `98,9%`. Escala 0..1; nunca recebe percentual. */
export function formatFraction(value: Maybe<number>, decimals = 1): string {
  if (value == null) return EMPTY;
  assertDecimalScale(value, 1, 'formatFraction');
  return numberFormat({ style: 'percent', ...fixed(decimals) }).format(value);
}

/** Retorno ou movimento em decimal, não anualizado (ex.: salto de evento 0.0435) → `4,35%`. */
export function formatReturn(value: Maybe<number>, decimals = 2): string {
  if (value == null) return EMPTY;
  assertDecimalScale(value, 1, 'formatReturn');
  return numberFormat({ style: 'percent', ...fixed(decimals) }).format(value);
}

/** Razão adimensional (ex.: moneyness K/F) → `1,05`. */
export function formatRatio(value: Maybe<number>, decimals = 2): string {
  if (value == null) return EMPTY;
  assertFinite(value, 'formatRatio');
  return numberFormat(fixed(decimals)).format(value);
}

/** Teto de sanidade para razões relativas (edge relativo, spread normal): 20 = 2.000%. */
export const MAX_DECIMAL_RELATIVE = 20;

/**
 * Edge relativo e spread normal (razão sobre a RV prevista, PRD §5.1) → `25,0%` ou `-47,5%`.
 * Diferente de `formatFraction`, aceita valores fora de 0..1 e negativos.
 */
export function formatRelative(value: Maybe<number>, decimals = 1): string {
  if (value == null) return EMPTY;
  assertDecimalScale(value, MAX_DECIMAL_RELATIVE, 'formatRelative');
  return numberFormat({ style: 'percent', ...fixed(decimals) }).format(value);
}

/** Taxa ou custo proporcional pequeno (decimal) → `0,134%` (até 4 casas, sem zeros à direita). */
export function formatSmallRate(value: Maybe<number>, maxDecimals = 4): string {
  if (value == null) return EMPTY;
  assertDecimalScale(value, 1, 'formatSmallRate');
  return numberFormat({ style: 'percent', minimumFractionDigits: 0, maximumFractionDigits: maxDecimals }).format(
    value,
  );
}

/*
 * Entradas de formulário (PRD-UI-03): o usuário digita em % ou em pontos de vol, como lê na tela;
 * a conversão para decimal acontece só aqui. Aceitam vírgula ou ponto; inválido → null.
 */

const INPUT_NUMBER = /^-?\d+([.,]\d+)?$/;

function parseInputNumber(raw: string): number | null {
  const text = raw.trim();
  if (!INPUT_NUMBER.test(text)) return null;
  const value = Number(text.replace(',', '.'));
  return Number.isFinite(value) ? value : null;
}

function roundDecimal(value: number): number {
  return Number(value.toPrecision(12)); // remove ruído binário de 0,134 / 100
}

/** "0,134" (%) → 0.00134. */
export function parsePercentInput(raw: string): number | null {
  const value = parseInputNumber(raw);
  return value == null ? null : roundDecimal(value / 100);
}

/** 0.00134 → "0,134" (para preencher o campo em %). */
export function toPercentInput(value: number): string {
  assertFinite(value, 'toPercentInput');
  return String(roundDecimal(value * 100)).replace('.', ',');
}

/** "1,5" (pontos de vol) → 0.015. */
export function parseVolPointsInput(raw: string): number | null {
  return parsePercentInput(raw);
}

/** 0.015 → "1,5" (pontos de vol). */
export function toVolPointsInput(value: number): string {
  return toPercentInput(value);
}

/** Número simples de formulário ("0,95", "20") → número; inválido → null. */
export function parsePlainInput(raw: string): number | null {
  return parseInputNumber(raw);
}

/** Número → texto de formulário com vírgula decimal. */
export function toPlainInput(value: number): string {
  assertFinite(value, 'toPlainInput');
  return String(roundDecimal(value)).replace('.', ',');
}

const MONEY_INPUT = /^\d{1,12}([.,]\d{1,6})?$/;

/**
 * Dinheiro digitado ("1,80", "R$ 42,67", "100000") → decimal exato em texto para a API ("1.80").
 * Sem separador de milhar; sem passar por float. Inválido ou não positivo → null.
 */
export function parseMoneyInput(raw: string): string | null {
  const text = raw.replace(/^\s*R\$\s*/, '').trim();
  if (!MONEY_INPUT.test(text)) return null;
  const normalized = text.replace(',', '.');
  return /^0+(\.0+)?$/.test(normalized) ? null : normalized;
}

/** Decimal da API ("1.80") → texto de formulário ("1,80"). */
export function toMoneyInput(value: string): string {
  if (!DECIMAL_STRING.test(value)) throw new RangeError(`toMoneyInput: "${value}" não é um decimal válido.`);
  return value.replace('.', ',');
}

const LOCAL_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** Agora no fuso da B3, no formato do `<input type="datetime-local">` ("2026-11-19T17:30"). */
export function nowMarketInput(now: Date = new Date()): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: MARKET_TIME_ZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(now)
      .map((p) => [p.type, p.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

/**
 * Data e hora digitadas no fuso da B3 → ISO com offset (America/Sao_Paulo é UTC−3 sem horário de
 * verão desde 2019). Inválido → null.
 */
export function marketInputToIso(local: string): string | null {
  return LOCAL_DATETIME.test(local) ? `${local}:00-03:00` : null;
}

/** Eixos em BRL nos gráficos (payoff e distribuição de P&L). */
export const CHART_MONEY_TICKPREFIX = 'R$ ';
export const CHART_MONEY_TICKFORMAT = ',.0f';
export const CHART_MONEY_HOVERFORMAT = ',.2f';

/**
 * Formatação dentro dos gráficos (Plotly usa d3-format): separadores do pt-BR e eixos de vol em
 * decimal exibidos como percentual. Ficam aqui para que nenhum componente formate por conta própria.
 */
export const CHART_SEPARATORS = ',.';
export const CHART_VOL_TICKFORMAT = '.0%';
/** Eixos de IV, com faixa estreita (smile, prazo constante): uma casa decimal. */
export const CHART_VOL_TICKFORMAT_FINE = '.1%';
export const CHART_VOL_HOVERFORMAT = '.2%';
export const CHART_RATIO_TICKFORMAT = '.2f';
export const CHART_DATE_TICKFORMAT = '%d/%m';
export const CHART_DATE_HOVERFORMAT = '%d/%m/%Y';
