import { NextResponse, type NextRequest } from 'next/server';
import { isLocalHost } from '@/lib/security/localHost';

/**
 * Guarda de Host do cockpit e do encaminhamento ao engine (PRD-NF-01, ADR-09).
 * Roda antes dos rewrites; o engine também confere Host/X-Forwarded-Host (defesa em camadas).
 * Ao hospedar (ADR-14), este arquivo passa a cuidar de autenticação.
 */
export function proxy(request: NextRequest) {
  if (!isLocalHost(request.headers.get('host'))) {
    return NextResponse.json(
      { type: 'about:blank', title: 'Bad Request', status: 400, detail: 'Host não permitido.' },
      { status: 400, headers: { 'content-type': 'application/problem+json' } },
    );
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/app', '/app/:path*', '/api/engine/:path*'],
};
