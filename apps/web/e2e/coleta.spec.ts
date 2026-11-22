import { expect, test } from '@playwright/test';

/**
 * Fluxo 1 (PRD §10.3): painel mostra pregões pendentes → disparar coleta → progresso →
 * relatório de lacunas. Roda contra a stack do E2E (`npm run engine:up:e2e`), com a fonte
 * SIMULADA por fixtures e "hoje" = 20/11/2026. Contra um engine com fonte real o teste é
 * pulado: ele dispararia downloads de verdade da B3.
 */
test('coleta: pendências → coletar → progresso → relatório de lacunas', async ({ page, request }) => {
  const health = await request.get('/api/engine/health');
  expect(health.ok()).toBeTruthy();
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(120_000);

  await page.goto('/app');
  const card = page.getByRole('region', { name: 'Pendências de coleta' });
  await expect(card).toContainText('com pendência, até 19/11/2026');
  await expect(card.getByText('Fonte simulada')).toBeVisible();

  const start = card.getByRole('button', { name: 'Coletar agora' });
  const follow = card.getByRole('link', { name: 'Acompanhar' });
  await expect(start.or(follow)).toBeVisible();
  if (await start.isVisible()) {
    await start.click();
  } else {
    await follow.click();
  }

  // Folga para a primeira compilação da rota em `next dev`.
  await expect(page).toHaveURL(/\/app\/coleta$/, { timeout: 30_000 });
  await expect(page.getByRole('heading', { level: 1, name: 'Coleta' })).toBeVisible();
  await expect(page.getByRole('progressbar', { name: 'Progresso da coleta' })).toBeVisible();

  // A fonte simulada cobre só parte da janela: a coleta termina com falhas reportadas.
  const status = page.getByRole('region', { name: 'Última coleta' }).getByRole('status');
  await expect(status).toHaveText(/Concluída com falhas/, { timeout: 90_000 });

  const gaps = page.getByRole('region', { name: 'Relatório de falhas e lacunas' });
  await expect(gaps.getByRole('table', { name: 'Lacunas por ativo e data' })).toBeVisible();
  await expect(gaps.getByRole('list', { name: 'Resumo por tipo' })).toContainText('Negócios do ativo com falha');
  // PETR4 em 19/11: OHLC oficial e R4 conferem; não há divergência no relatório.
  await expect(gaps).not.toContainText('R4 diverge do oficial');

  // De volta ao painel: a última coleta aparece no estado do engine.
  await page.getByRole('link', { name: 'Painel' }).click();
  await expect(page.getByRole('region', { name: 'Engine' }).getByText('nenhuma ainda')).toHaveCount(0);
});
