import { NextResponse, type NextRequest } from 'next/server';
import { isCrossSiteWrite, isLocalHost } from '@/lib/security/localHost';

/**
 * Guarda de Host e de CSRF do cockpit e do encaminhamento ao engine (PRD-NF-01, ADR-09).
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
  const { headers } = request;
  if (isCrossSiteWrite(request.method, headers.get('origin'), headers.get('sec-fetch-site'))) {
    return NextResponse.json(
      { type: 'about:blank', title: 'Forbidden', status: 403, detail: 'Requisição de outra origem recusada.' },
      { status: 403, headers: { 'content-type': 'application/problem+json' } },
    );
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/app', '/app/:path*', '/api/engine/:path*'],
};
