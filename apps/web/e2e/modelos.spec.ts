import { expect, test, type APIRequestContext } from '@playwright/test';

/**
 * Etapa 4: tela de modelos (PRD 1.7 §8.1; RF-PRV-01..04, CS-03), contra a stack do E2E com a fonte
 * SIMULADA (fixtures; "hoje" = 20/11/2026). Pulado contra engine com fonte real.
 *
 * Fixtures: 220 retornos → EWMA com 7 janelas (< 8, dados insuficientes), combinação com 9 (elegível),
 * GARCH sem amostra (mínimo de 240 retornos).
 */
async function ensureForecasts(request: APIRequestContext): Promise<void> {
  const deadline = Date.now() + 180_000;
  for (;;) {
    const pending = await (await request.get('/api/engine/collection/pending')).json();
    const res = await request.get('/api/engine/forecasts?underlying=PETR4');
    const ready = res.ok() && (await res.json()).items.length > 0;
    if (ready && !pending.active_run) return;
    if (!pending.active_run && !pending.last_run) {
      await request.post('/api/engine/collection/runs');
    }
    if (Date.now() > deadline) throw new Error('A previsão não ficou pronta a tempo.');
    await new Promise((r) => setTimeout(r, 2_000));
  }
}

test('modelos: previsão com intervalo, avaliação × baselines e escolha do modelo do edge', async ({
  page,
  request,
}) => {
  const health = await request.get('/api/engine/health');
  expect(health.ok()).toBeTruthy();
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(300_000);
  await ensureForecasts(request);

  await page.goto('/app');
  await page.getByRole('link', { name: 'Modelos' }).first().click();
  await expect(page.getByRole('heading', { level: 1, name: 'Modelos' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Ativo' }).selectOption('PETR4');

  const forecast = page.getByRole('region', { name: 'RV prevista' });
  await expect(forecast.getByRole('row', { name: /GARCH/ })).toContainText('dados insuficientes');
  await expect(forecast.getByRole('row', { name: /^EWMA/ })).toContainText('%');

  const evaluation = page.getByRole('region', { name: 'Erro de previsão × baselines' });
  await expect(evaluation.getByRole('row', { name: /^EWMA/ })).toContainText('dados insuficientes');
  await expect(evaluation.getByRole('row', { name: /Combinação/ })).toContainText('pts');

  await expect(page.getByRole('img', { name: /RV realizada em cada janela não sobreposta/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Share chart|Chart Studio/ })).toHaveCount(0);

  // Escolha do modelo do edge (RF-PRV-04): só a combinação é elegível nas fixtures. A escolha cria uma
  // versão nova de configuração e não volta para a EWMA (que não é elegível), então o teste aceita
  // as duas situações de partida.
  const combination = forecast.getByRole('row', { name: /Combinação/ });
  const button = combination.getByRole('button', { name: 'Usar no edge' });
  if (await button.isVisible()) await button.click();
  await expect(forecast).toContainText('Modelo em uso no edge: Combinação de estimadores');
  await expect(combination).toContainText('em uso');
});
