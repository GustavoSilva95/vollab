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

const SAFE_METHODS: ReadonlySet<string> = new Set(['GET', 'HEAD', 'OPTIONS']);

/**
 * CSRF (revisão de segurança da Etapa 2, M-3): uma página de outro site pode mandar POST para
 * 127.0.0.1 (form ou `fetch` no-cors) e disparar a coleta. Métodos que alteram estado só são
 * aceitos sem `Origin` (clientes fora do navegador) ou com `Origin` local, e nunca `cross-site`.
 */
export function isCrossSiteWrite(method: string, origin: string | null, secFetchSite: string | null): boolean {
  if (SAFE_METHODS.has(method.toUpperCase())) return false;
  if (secFetchSite?.toLowerCase() === 'cross-site') return true;
  if (origin === null) return false;
  if (origin === 'null') return true;
  try {
    return !LOCAL_HOSTNAMES.has(hostnameOf(new URL(origin).host));
  } catch {
    return true;
  }
}
