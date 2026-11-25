// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isActiveRoute } from '@/lib/cockpit/routes';
import AppNav from './AppNav';

const pathname = vi.hoisted(() => ({ current: '/app' }));
vi.mock('next/navigation', () => ({ usePathname: () => pathname.current }));

afterEach(cleanup);

describe('AppNav', () => {
  it('marca o painel como página atual', () => {
    pathname.current = '/app';
    render(<AppNav />);
    expect(screen.getByRole('link', { name: 'Painel' })).toHaveAttribute('aria-current', 'page');
  });

  it('telas de etapas futuras aparecem desabilitadas, sem link', () => {
    render(<AppNav />);
    expect(screen.queryByRole('link', { name: /Performance/ })).not.toBeInTheDocument();
    const performance = screen.getByText('Performance').closest('[aria-disabled]');
    expect(performance).toHaveAttribute('title', 'Disponível na Etapa 9');
  });

  it('Ranking e Configurações (Etapa 5) já são links', () => {
    render(<AppNav />);
    expect(screen.getByRole('link', { name: 'Ranking' })).toHaveAttribute('href', '/app/ranking');
    expect(screen.getByRole('link', { name: 'Configurações' })).toHaveAttribute('href', '/app/configuracoes');
  });

  it('Simulador (Etapa 6) já é um link', () => {
    render(<AppNav />);
    expect(screen.getByRole('link', { name: 'Simulador' })).toHaveAttribute('href', '/app/simulador');
  });

  it('Carteira e Diário (Etapa 7) já são links', () => {
    render(<AppNav />);
    expect(screen.getByRole('link', { name: 'Carteira' })).toHaveAttribute('href', '/app/carteira');
    expect(screen.getByRole('link', { name: 'Diário' })).toHaveAttribute('href', '/app/diario');
  });

  it('Coleta (Etapa 2) já é um link', () => {
    pathname.current = '/app/coleta';
    render(<AppNav />);
    expect(screen.getByRole('link', { name: 'Coleta' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('isActiveRoute', () => {
  it('painel só por correspondência exata; demais por prefixo', () => {
    expect(isActiveRoute('/app', '/app')).toBe(true);
    expect(isActiveRoute('/app/coleta', '/app')).toBe(false);
    expect(isActiveRoute('/app/operacoes/12', '/app/operacoes')).toBe(true);
    expect(isActiveRoute('/app/operacoesx', '/app/operacoes')).toBe(false);
  });
});
