import { expect, test } from '@playwright/test';
import { ensureForecasts } from './helpers';

/**
 * Fluxo 2 (PRD §10.3; Etapa 6): ranking → ativo → simulador com preço manual → dimensionamento →
 * registrar entrada → o retrato gravado contém semáforo, configuração e modelo. Contra a stack do
 * E2E com a fonte SIMULADA; pulado contra engine com fonte real.
 *
 * Fixtures: com a combinação, PETR4 dá edge de compra de vol; o straddle comprado tem tamanho
 * positivo pelo Kelly ou pelo teto.
 */
test('decisão de entrada: simular, dimensionar e registrar com retrato da decisão', async ({ page, request }) => {
  const health = await request.get('/api/engine/health');
  expect(health.ok()).toBeTruthy();
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(300_000);
  await ensureForecasts(request);
  expect((await request.put('/api/engine/models/selection', { data: { model: 'combination' } })).ok()).toBeTruthy();

  // Ranking → ativo → simulador.
  await page.goto('/app/ranking');
  await page.getByTestId('ranking-row-PETR4').getByRole('link', { name: 'PETR4' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'PETR4' })).toBeVisible();
  await page.getByRole('link', { name: 'Simular estrutura em PETR4' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Simulador' })).toBeVisible();

  // Straddle comprado com o preço do ativo informado à mão (RF-SIM-03) e capital.
  const form = page.getByRole('form', { name: 'Simular estrutura' });
  await form.getByLabel('Estrutura').selectOption('long_straddle');
  await form.getByLabel('Ativo-objeto (R$)').fill('42,67');
  await form.getByLabel('Capital para opções (R$)').fill('100000');
  await form.getByRole('button', { name: 'Simular e dimensionar' }).click();

  const edge = page.getByTestId('sim-edge');
  await expect(edge).toContainText('Edge líquido (comprar vol)', { timeout: 30_000 });
  await expect(edge).toContainText('manual');
  await expect(page.getByTestId('sim-distribution')).toContainText('P&L esperado líquido por lote');
  const sizing = page.getByTestId('sim-sizing');
  await expect(sizing.getByTestId('sim-size-rule')).toHaveText(/Prevaleceu o (Kelly fracionado|teto de perda)|empatados/);
  const suggested = Number(await sizing.getByTestId('sim-size-final').innerText());
  expect(suggested).toBeGreaterThan(0);

  // Registrar a entrada dentro da regra (lotes = sugerido): sem justificativa.
  const entry = page.getByRole('form', { name: 'Registrar entrada' });
  await expect(entry.getByLabel('Lotes executados')).toHaveValue(String(suggested));
  await entry.getByRole('button', { name: 'Registrar entrada' }).click();

  const done = page.getByTestId('sim-registered');
  await expect(done).toBeVisible({ timeout: 30_000 });
  await expect(done.getByTestId('snapshot-state')).toHaveText('Edge líquido');
  await expect(done.getByTestId('snapshot-model')).toHaveText('Combinação de estimadores');
  await expect(done.getByTestId('snapshot-config')).toHaveText(/^v\d+$/);

  // O retrato gravado (lido do engine) contém semáforo, configuração, modelo e a entrada manual.
  const id = (await done.getByRole('heading').innerText()).match(/operação (\d+)/i)?.[1];
  expect(id).toBeTruthy();
  const pos = await (await request.get(`/api/engine/positions/${id}`)).json();
  expect(pos.decision_snapshot.simulation.state).toBe('edge');
  expect(pos.decision_snapshot.simulation.model).toBe('combination');
  expect(pos.decision_snapshot.simulation.config_version_id).toBe(pos.config_version_id);
  expect(pos.decision_snapshot.sizing.n_final).toBe(suggested);
  expect(pos.manual_inputs.map((m: { kind: string }) => m.kind)).toContain('spot');
});

/**
 * Rolagem pelo simulador (PRD 1.11 §5.10 e §8.1; RN-GES-04): aberto com `?roll_from=`, mostra a
 * origem, pede o fechamento das pernas em aberto e grava a saída da origem ligada à nova entrada, que
 * passa pelo semáforo (CS-01).
 */
test('rolagem: simulador com a origem, fechamento das pernas e nova entrada ligada', async ({ page, request }) => {
  const health = await request.get('/api/engine/health');
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(300_000);
  await ensureForecasts(request);
  expect((await request.put('/api/engine/models/selection', { data: { model: 'combination' } })).ok()).toBeTruthy();

  const register = async (url: string, button: string, closePrice = false): Promise<string> => {
    await page.goto(url);
    const form = page.getByRole('form', { name: 'Simular estrutura' });
    await expect(form.getByLabel('Estrutura')).toHaveValue('long_straddle', { timeout: 30_000 }).catch(async () => {
      await form.getByLabel('Estrutura').selectOption('long_straddle');
    });
    await form.getByLabel('Capital para opções (R$)').fill('100000');
    await form.getByRole('button', { name: 'Simular e dimensionar' }).click();
    await expect(page.getByTestId('sim-edge')).toContainText('Edge líquido', { timeout: 30_000 });
    const entry = page.getByRole('form', { name: 'Registrar entrada' });
    await entry.getByLabel('Lotes executados').fill('1');
    if (closePrice) {
      // A origem acabou de entrar (sem marcação D-1 ainda): o preço de fechamento vem vazio.
      const close = entry.getByRole('group', { name: /Fechamento da operação/ });
      for (const input of await close.getByLabel(/Preço de fechamento/).all()) await input.fill('1,50');
    }
    await entry.getByRole('button', { name: button }).click();
    const done = page.getByTestId('sim-registered');
    await expect(done).toBeVisible({ timeout: 30_000 });
    return (await done.getByRole('heading').innerText()).match(/operação (\d+)/i)?.[1] as string;
  };

  const origin = await register('/app/simulador?ticker=PETR4', 'Registrar entrada');
  expect(origin).toBeTruthy();

  await page.goto(`/app/simulador?ticker=PETR4&roll_from=${origin}&expiry=2026-12-18&structure=long_straddle`);
  await expect(page.getByTestId('sim-roll-origin')).toContainText(`Rolagem da operação #${origin}`);
  const rolled = await register(
    `/app/simulador?ticker=PETR4&roll_from=${origin}&expiry=2026-12-18&structure=long_straddle`,
    'Registrar a rolagem',
    true,
  );
  const newPos = await (await request.get(`/api/engine/positions/${rolled}`)).json();
  expect(newPos.rolled_from_position_id).toBe(Number(origin));
  const old = await (await request.get(`/api/engine/positions/${origin}`)).json();
  expect(old.status).toBe('closed');
  expect(old.entries.filter((e: { kind: string }) => e.kind === 'roll')).toHaveLength(2);

  // Encerra a nova posição (a carteira volta vazia para os outros fluxos).
  for (const h of newPos.holdings as { instrument: string; quantity: number }[]) {
    if (h.quantity === 0) continue;
    const r = await request.post(`/api/engine/positions/${rolled}/entries`, {
      data: { kind: 'exit', instrument: h.instrument, quantity: -h.quantity, price_brl: '1.00', executed_at: new Date().toISOString() },
    });
    expect(r.status()).toBe(201);
  }
});
