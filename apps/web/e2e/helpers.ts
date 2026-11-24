import type { APIRequestContext } from '@playwright/test';

/** Espera a coleta das fixtures e a previsão de PETR4 (dispara a coleta se nunca rodou). */
export async function ensureForecasts(request: APIRequestContext): Promise<void> {
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
