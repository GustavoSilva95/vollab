import { expect, test } from '@playwright/test';
import { ensureForecasts } from './helpers';

/**
 * Fluxo 3 (PRD 1.10 e 1.11 §10.3; Etapas 7 e 8): registrar a entrada → lançar hedge → marcação D-1 →
 * atribuição com o resíduo visível → alerta persistente de banda de delta no painel → marcar como visto
 * → hedge até a borda → o alerta resolve sozinho depois da nova marcação.
 *
 * Fixtures ("hoje" = 20/11/2026, último pregão 19/11): a entrada é registrada com execução em 17/11
 * (registro de uma operação feita antes) para haver três pregões de marcação (17, 18 e 19/11) com os
 * dados reais já salvos. Pulado contra engine com fonte real.
 */
test('vida da operação: hedge, marcação D-1, atribuição com resíduo e alerta de banda', async ({ page, request }) => {
  const health = await request.get('/api/engine/health');
  expect(health.ok()).toBeTruthy();
  const { data_source: dataSource } = (await health.json()) as { data_source?: string };
  test.skip(dataSource !== 'fixtures', 'Engine com fonte real: suba a stack do E2E (npm run engine:up:e2e).');
  test.setTimeout(300_000);
  await ensureForecasts(request);
  expect((await request.put('/api/engine/models/selection', { data: { model: 'combination' } })).ok()).toBeTruthy();

  // Entrada pelo simulador (o semáforo é obrigatório, CS-01), executada em 17/11.
  await page.goto('/app/simulador?ticker=PETR4');
  const form = page.getByRole('form', { name: 'Simular estrutura' });
  await form.getByLabel('Estrutura').selectOption('long_straddle');
  await form.getByLabel('Capital para opções (R$)').fill('100000');
  // Outro teste em paralelo pode criar uma versão de configuração entre simular e registrar: o engine
  // responde 409 ("a configuração mudou") e o usuário simula de novo.
  for (let attempt = 0; ; attempt++) {
    await form.getByRole('button', { name: 'Simular e dimensionar' }).click();
    await expect(page.getByTestId('sim-edge')).toContainText('Edge líquido', { timeout: 30_000 });
    await expect(page.getByTestId('sim-limits')).toContainText('pró-forma');
    const entry = page.getByRole('form', { name: 'Registrar entrada' });
    // Um lote: o hedge de −50 ações abaixo põe o delta fora da banda (± 0,10 × 100 × 1 = ± 10 ações).
    await entry.getByLabel('Lotes executados').fill('1');
    await entry.getByLabel('Executado em (Brasília)').fill('2026-11-17T15:00');
    await entry.getByRole('button', { name: 'Registrar entrada' }).click();
    const done = page.getByTestId('sim-registered');
    const changed = page.getByText('A configuração mudou desde a simulação');
    await expect(done.or(changed)).toBeVisible({ timeout: 30_000 });
    if (await done.isVisible()) break;
    expect(attempt).toBeLessThan(3);
  }
  await page.getByTestId('sim-open-position').click();
  await expect(page.getByRole('heading', { level: 1, name: /Operação \d+/ })).toBeVisible();
  const id = page.url().match(/operacoes\/(\d+)/)?.[1];
  expect(id).toBeTruthy();

  // Marcação D-1 feita pelo worker: três pregões, atribuição em cada um.
  await expect
    .poll(async () => (await (await request.get(`/api/engine/positions/${id}`)).json()).attribution.length, {
      timeout: 60_000,
    })
    .toBe(3);

  // Lançar hedge em 18/11 (ação vendida) pelo formulário da operação.
  await page.reload();
  const launch = page.getByRole('form', { name: 'Novo lançamento' });
  await launch.getByLabel('Tipo').selectOption('hedge');
  await launch.getByLabel('Quantidade (+ compra, − venda)').fill('-50');
  await launch.getByLabel('Preço executado (R$)').fill('43,10');
  await launch.getByLabel('Taxas e corretagem (R$)').fill('0,65');
  await launch.getByLabel('Executado em (Brasília)').fill('2026-11-18T14:00');
  await launch.getByRole('button', { name: 'Lançar' }).click();
  await expect(page.getByRole('status')).toContainText('Lançamento gravado');
  await expect(page.getByTestId('op-entries')).toContainText('Hedge');

  // A marcação é refeita com o hedge: ações a partir de 18/11 e a execução do hedge na atribuição.
  await expect
    .poll(
      async () => {
        const pos = await (await request.get(`/api/engine/positions/${id}`)).json();
        return pos.marks.map((m: { stock_qty: number }) => m.stock_qty);
      },
      { timeout: 60_000 },
    )
    .toEqual([0, -50, -50]);

  await page.reload();
  const attribution = page.getByTestId('op-attribution');
  await expect(attribution.getByRole('columnheader', { name: 'Resíduo' })).toBeVisible();
  await expect(attribution.getByRole('columnheader', { name: 'Execução e custos' })).toBeVisible();
  await expect(attribution).toContainText('19/11/2026');
  await expect(attribution).toContainText('Acumulado');
  await expect(page.getByTestId('op-cs04')).not.toHaveText('—');
  await expect(page.getByTestId('op-delta-band')).toHaveAttribute('data-state', 'outside');
  await expect(page.getByTestId('op-delta-band')).toContainText('Fora da banda');

  // Etapa 8: o worker abre o alerta persistente de banda (RN-GES-01) depois da marcação.
  type Alert = { id: number; rule: string; state: string; details: { adjust_shares?: number } };
  const bandAlert = async (): Promise<Alert | undefined> => {
    const res = await request.get(`/api/engine/alerts?position_id=${id}&state=all`);
    return ((await res.json()).alerts as Alert[]).find((a) => a.rule === 'hedge_band');
  };
  await expect.poll(async () => (await bandAlert())?.state, { timeout: 60_000 }).toBe('active');
  const alert = (await bandAlert()) as Alert;
  const adjust = alert.details.adjust_shares ?? 0;
  expect(adjust).toBeGreaterThan(0); // delta negativo: comprar ações até a borda

  await page.goto('/app');
  const card = page.getByTestId('dash-alerts');
  const item = card.getByTestId('alert-hedge_band').filter({ hasText: `#${id}` });
  await expect(item).toContainText('Delta fora da banda');
  await expect(item).toContainText('não calibrado');
  await expect(item).toContainText(/comprar\s\d+\sações/);
  await item.getByRole('button', { name: 'Marcar como visto' }).click();
  await expect(item.getByTestId('alert-state')).toHaveText('Visto');

  // Hedge até a borda, em 19/11, pela tela da operação.
  await page.goto(`/app/operacoes/${id}`);
  await expect(page.getByTestId('op-management')).toContainText('Delta fora da banda');
  const hedge = page.getByRole('form', { name: 'Novo lançamento' });
  await hedge.getByLabel('Tipo').selectOption('hedge');
  await hedge.getByLabel('Quantidade (+ compra, − venda)').fill(String(adjust));
  await hedge.getByLabel('Preço executado (R$)').fill('42,67');
  await hedge.getByLabel('Executado em (Brasília)').fill('2026-11-19T15:00');
  await hedge.getByRole('button', { name: 'Lançar' }).click();
  await expect(page.getByRole('status')).toContainText('Lançamento gravado');
  await expect.poll(async () => (await bandAlert())?.state, { timeout: 60_000 }).toBe('resolved');
  await page.reload();
  await expect(page.getByTestId('rule-hedge_band')).toContainText('OK');
  await expect(page.getByTestId('op-delta-band')).toHaveAttribute('data-state', 'inside');

  // Diário e carteira mostram a operação aberta.
  await page.goto('/app/diario');
  await expect(page.getByTestId(`journal-row-${id}`)).toContainText('Aberta');
  await page.goto('/app/carteira');
  await expect(page.getByTestId('pf-greeks')).toContainText('PETR4');
  await expect(page.getByTestId('pf-stress')).toContainText('Queda do ativo com alta de vol');

  // Encerramento (saída de cada quantidade em aberto, em 19/11): status derivado "Encerrada" e a
  // carteira volta vazia para os outros fluxos (os limites pró-forma dependem dela).
  const pos = await (await request.get(`/api/engine/positions/${id}`)).json();
  for (const h of pos.holdings as { instrument: string; quantity: number }[]) {
    if (h.quantity === 0) continue;
    const r = await request.post(`/api/engine/positions/${id}/entries`, {
      data: {
        kind: 'exit',
        instrument: h.instrument,
        quantity: -h.quantity,
        price_brl: h.instrument === 'PETR4' ? '42.67' : '1.00',
        executed_at: '2026-11-19T16:30:00-03:00',
      },
    });
    expect(r.status()).toBe(201);
  }
  await page.goto('/app/diario');
  await expect(page.getByTestId(`journal-row-${id}`)).toContainText('Encerrada');
});
