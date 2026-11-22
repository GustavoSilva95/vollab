import type { CreateClientConfig } from './generated/client.gen';

/**
 * Configuração em tempo de execução do cliente gerado (ADR-09). Escrita à mão; não é gerada.
 *
 * - No navegador: `/api/engine`, na mesma origem; o Next encaminha ao engine (rewrites).
 * - No servidor (Server Components): direto na URL interna do engine.
 */
export const ENGINE_BROWSER_BASE_URL = '/api/engine';

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl:
    typeof window === 'undefined'
      ? (process.env.ENGINE_URL ?? 'http://127.0.0.1:8000')
      : ENGINE_BROWSER_BASE_URL,
});
