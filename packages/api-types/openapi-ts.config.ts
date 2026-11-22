import { defineConfig } from '@hey-api/openapi-ts';

/**
 * Contrato gerado do OpenAPI do engine (ADR-10, PRD-QA-01).
 * Entrada: openapi.json, exportado do FastAPI por `npm run contract:openapi`.
 * Saída: src/generated (versionada; o CI falha se divergir — job contract-drift).
 */
export default defineConfig({
  input: './openapi.json',
  output: { path: './src/generated' },
  plugins: [
    { name: '@hey-api/client-fetch', runtimeConfigPath: './src/runtime-config' },
    '@hey-api/typescript',
    // timestamptz chega com offset (ex.: -03:00, sessão do Postgres em America/Sao_Paulo);
    // RFC 3339 permite offset, e o Zod padrão só aceitaria `Z`.
    { name: 'zod', dates: { offset: true } },
    { name: '@hey-api/sdk', validator: true },
    '@tanstack/react-query',
  ],
});
