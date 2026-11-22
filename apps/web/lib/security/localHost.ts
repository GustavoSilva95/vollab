/**
 * Fase 1 é local (PRD-NF-01): o web só atende pelo próprio computador. Recusar `Host`
 * estranho bloqueia DNS rebinding, em que um site religa o próprio domínio para 127.0.0.1.
 */
export const LOCAL_HOSTNAMES: ReadonlySet<string> = new Set(['localhost', '127.0.0.1', '[::1]']);

/** Extrai o hostname (sem porta) de um cabeçalho Host. */
export function hostnameOf(hostHeader: string): string {
  const value = hostHeader.trim().toLowerCase();
  if (value.startsWith('[')) return value.slice(0, value.indexOf(']') + 1);
  const colon = value.indexOf(':');
  return colon === -1 ? value : value.slice(0, colon);
}

export function isLocalHost(hostHeader: string | null): boolean {
  return hostHeader !== null && LOCAL_HOSTNAMES.has(hostnameOf(hostHeader));
}
