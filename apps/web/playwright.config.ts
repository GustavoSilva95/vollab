import { defineConfig, devices } from '@playwright/test';

/**
 * E2E (PRD §10.3). Exige o engine no ar (`npm run engine:up`); o Next é iniciado aqui.
 * Os fluxos críticos 1–3 entram nas Etapas 2, 6 e 7; na Etapa 1 só a fumaça da casca.
 */
const PORT = Number(process.env.E2E_PORT ?? 3000);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    // Fluxo 1 (coleta) primeiro: os demais usam os dados que ele coleta na stack do E2E.
    { name: 'coleta', testMatch: /coleta\.spec\.ts/, use: { ...devices['Desktop Chrome'] } },
    {
      name: 'chromium',
      testIgnore: /coleta\.spec\.ts/,
      dependencies: ['coleta'],
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npx next start -p ${PORT} -H 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
