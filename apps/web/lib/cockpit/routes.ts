/**
 * Telas do cockpit (PRD §8.1) e a etapa do PLANO em que cada uma fica pronta.
 * A navegação mostra todas; as ainda não construídas aparecem desabilitadas.
 */
export interface CockpitRoute {
  href: string;
  label: string;
  /** Etapa do PLANO.md que entrega a tela. */
  stage: number;
  available: boolean;
}

export const COCKPIT_ROUTES: readonly CockpitRoute[] = [
  { href: '/app', label: 'Painel', stage: 1, available: true },
  { href: '/app/coleta', label: 'Coleta', stage: 2, available: true },
  { href: '/app/ativos', label: 'Ativos', stage: 3, available: true },
  { href: '/app/ranking', label: 'Ranking', stage: 5, available: true },
  { href: '/app/simulador', label: 'Simulador', stage: 6, available: true },
  { href: '/app/carteira', label: 'Carteira', stage: 7, available: true },
  { href: '/app/diario', label: 'Diário', stage: 7, available: true },
  { href: '/app/performance', label: 'Performance', stage: 9, available: false },
  { href: '/app/modelos', label: 'Modelos', stage: 4, available: true },
  { href: '/app/eventos', label: 'Eventos', stage: 3, available: true },
  { href: '/app/configuracoes', label: 'Configurações', stage: 5, available: true },
];

/** Rota ativa: correspondência exata para o painel, por prefixo para as demais. */
export function isActiveRoute(pathname: string, href: string): boolean {
  if (href === '/app') return pathname === '/app';
  return pathname === href || pathname.startsWith(`${href}/`);
}
