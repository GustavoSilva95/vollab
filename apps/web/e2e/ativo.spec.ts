import { expect, test, type APIRequestContext } from '@playwright/test';

/**
 * Etapa 3: tela do ativo e calendário de eventos (PRD §8.1), contra a stack do E2E com a fonte
 * SIMULADA (fixtures; "hoje" = 20/11/2026). Pulado contra engine com fonte real.
 */
async function ensureCollected(request: APIRequestContext): Promise<void> {
  const deadline = Date.now() + 150_000;
  for (;;) {
    const pending = await (await request.get('/api/engine/collection/pending')).json();
    const realized = await request.get('/api/engine/underlyings/PETR4/vol/realized');
    const hasRv = realized.ok() && (await realized.json()).estimators.length > 0;
    if (hasRv && !pending.active_run) return;
    // Sem coleta nenhuma (teste rodado isolado): dispara; normalmente o projeto `coleta` já rodou.
    if (!pending.active_run && !pending.last_run) {
      await request.post('/api/engine/collection/runs');
    }
    if (Date.now() > deadline) throw new Error('A coleta simulada não terminou a tempo.');
    await new Promise((r) => setTimeout(r, 2_000));
  }
}

test('ativo: RV lado a lado, IV, smile e evento cadastrado', async ({ page, request }) => {
  const health = await request.get('/api/engine/health');
  expect(health.ok()).toBeTruthy();
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(240_000);
  await ensureCollected(request);

  await page.goto('/app/ativos');
  await page.getByRole('link', { name: 'PETR4' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'PETR4' })).toBeVisible();

  const rv = page.getByRole('region', { name: 'Volatilidade realizada' });
  await expect(rv.getByRole('row', { name: /Yang-Zhang/ })).toContainText('%');
  // Intradiária com 11 pregões nas fixtures: janela de 20 sem número (PRD-UI-08).
  await expect(rv.getByRole('row', { name: /Intradiária/ })).toContainText('dados insuficientes');
  await expect(page.getByRole('img', { name: /Volatilidade realizada por estimador/ })).toBeVisible();

  const cm = page.getByRole('region', { name: 'IV ATM de prazo constante' });
  await expect(cm).toContainText('prazo efetivo');
  await expect(page.getByRole('img', { name: /Smile: IV por moneyness/ })).toBeVisible();
  // Nenhum botão do Plotly que envie dados para fora (PRD-NF-01).
  await expect(page.getByRole('button', { name: /Share chart|Chart Studio/ })).toHaveCount(0);

  // Evento pela tela de eventos e o salto na tela do ativo.
  await page.getByRole('link', { name: 'Eventos' }).first().click();
  const form = page.getByRole('region', { name: 'Novo evento' });
  await form.getByRole('combobox', { name: 'Ativo' }).selectOption('PETR4');
  await form.getByLabel('Data (pregão afetado)').fill('2026-12-10');
  const note = `e2e-${Date.now()}`;
  await form.getByRole('textbox', { name: 'Nota' }).fill(note);
  await form.getByRole('button', { name: 'Cadastrar' }).click();
  const calendar = page.getByRole('region', { name: 'Calendário' });
  const row = calendar.getByRole('row', { name: new RegExp(`10/12/2026.*Resultado.*${note}`) });
  await expect(row).toBeVisible();

  await page.goto('/app/ativos/PETR4');
  await expect(page.getByRole('region', { name: 'Salto de eventos (resultados)' })).toContainText('10/12/2026');

  // Limpa para a próxima execução.
  await page.goto('/app/eventos');
  const again = page.getByRole('region', { name: 'Calendário' }).getByRole('row', { name: new RegExp(`10/12/2026.*Resultado.*${note}`) });
  await again.getByRole('button', { name: /Apagar/ }).click();
  await expect(again).toHaveCount(0);
});
