import { expect, test } from '@playwright/test';

test('landing continua no ar', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: 'Leia a volatilidade antes do mercado' })).toBeVisible();
});

test('/entrar leva ao cockpit, que fala com o engine pelo rewrite', async ({ page }) => {
  await page.goto('/entrar');
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Painel' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Painel' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('status')).toHaveText('Engine online');
});

test('/cadastro mostra "em breve"', async ({ page }) => {
  await page.goto('/cadastro');
  await expect(page.getByText('Em breve', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { level: 1, name: 'Cadastro' })).toBeVisible();
});
