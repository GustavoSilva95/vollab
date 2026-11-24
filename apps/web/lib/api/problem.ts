/** Mensagem de um erro RFC 9457 do engine (`detail`), ou o texto padrão. Módulo leve, sem dependência
 * de tela: as rotas que o usam não carregam o código de outras (revisão de performance da Etapa 7, M-8). */
export function problemMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  return fallback;
}
