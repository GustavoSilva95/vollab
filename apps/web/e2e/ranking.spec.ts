import { expect, test, type APIRequestContext } from '@playwright/test';

/**
 * Etapa 5: ranking e configuração versionada (PRD 1.8 §8.1 e §10.2; RF-RNK-01/02, RN-EDG-03..07), contra
 * a stack do E2E com a fonte SIMULADA (fixtures; "hoje" = 20/11/2026). Pulado contra engine com fonte real.
 *
 * Fixtures: só PETR4 tem IV (fallback da ATM de 18/12, "aproximado"); a combinação é o único modelo com
 * avaliação suficiente; spread normal e limiar não calibrados.
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

async function saveThreshold(page: import('@playwright/test').Page, points: string, note: string): Promise<void> {
  await page.goto('/app/configuracoes');
  await expect(page.getByRole('heading', { level: 1, name: 'Configurações' })).toBeVisible();
  await page.getByLabel('Limiar de edge (pontos de vol)').fill(points);
  await page.getByLabel('Nota da versão').fill(note);
  await page.getByRole('button', { name: 'Salvar nova versão' }).click();
  await expect(page.getByRole('status')).toContainText(/Versão .* criada|Nada mudou/);
}

test('ranking: semáforo com rótulos, link para o ativo e configuração versionada mudando o ranking', async ({
  page,
  request,
}) => {
  const health = await request.get('/api/engine/health');
  expect(health.ok()).toBeTruthy();
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(300_000);
  await ensureForecasts(request);
  // O modelo do edge precisa de avaliação no ativo; nas fixtures só a combinação tem (idempotente).
  expect((await request.put('/api/engine/models/selection', { data: { model: 'combination' } })).ok()).toBeTruthy();

  await page.goto('/app');
  await page.getByRole('link', { name: 'Ranking' }).first().click();
  await expect(page.getByRole('heading', { level: 1, name: 'Ranking' })).toBeVisible();
  const petr = page.getByTestId('ranking-row-PETR4');
  await expect(petr).toContainText(/Edge líquido|Inconclusivo|Sem edge/);
  await expect(petr).toContainText('não calibrado');
  await expect(petr).toContainText('aproximado');
  await expect(page.getByTestId('ranking-row-BBAS3')).toContainText('Indisponível');

  // Detalhe da linha: custos discriminados.
  await page.getByRole('button', { name: 'Detalhes de PETR4' }).click();
  await expect(page.getByText(/Hedge \(Leland/)).toBeVisible();

  // Configuração versionada: um limiar de 20 pontos impede edge líquido nas duas direções.
  await saveThreshold(page, '20', 'E2E: limiar alto');
  await page.getByRole('link', { name: 'Ranking' }).first().click();
  await expect(page.getByRole('region', { name: 'Ranking' })).toContainText('Limiar 20,0 pts');
  await expect(page.getByTestId('ranking-row-PETR4')).toContainText(/Inconclusivo|Sem edge/);
  await expect(page.getByTestId('ranking-row-PETR4')).not.toContainText('Edge líquido');

  // Volta ao padrão (outra versão nova; nada é alterado no lugar).
  await saveThreshold(page, '1', 'E2E: limiar padrão');
  await page.goto('/app/ranking');
  await expect(page.getByRole('region', { name: 'Ranking' })).toContainText('Limiar 1,0 pts');

  // Ranking → ativo.
  await page.getByTestId('ranking-row-PETR4').getByRole('link', { name: 'PETR4' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'PETR4' })).toBeVisible();
});
