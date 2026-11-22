import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { hostnameOf, isCrossSiteWrite, isLocalHost } from './localHost';

describe('isLocalHost (DNS rebinding, PRD-NF-01)', () => {
  it.each(['localhost:3000', '127.0.0.1:3000', '127.0.0.1', '[::1]:3000', 'LOCALHOST'])('aceita %s', (host) => {
    expect(isLocalHost(host)).toBe(true);
  });

  it.each(['evil.example:3000', '192.168.0.10:3000', 'localhost.evil.example', '', null])('recusa %s', (host) => {
    expect(isLocalHost(host)).toBe(false);
  });

  it('extrai hostname de IPv6 com porta', () => {
    expect(hostnameOf('[::1]:3000')).toBe('[::1]');
  });
});

describe('scripts do Next (PRD-NF-01)', () => {
  // O padrão do Next 16 é 0.0.0.0: sem -H, o cockpit e o rewrite ficam abertos na rede local.
  const pkg = JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8')) as {
    scripts: Record<string, string>;
  };

  it.each(['dev', 'start'])('"%s" escuta só em 127.0.0.1', (name) => {
    expect(pkg.scripts[name]).toMatch(/\s-H 127\.0\.0\.1(\s|$)/);
  });
});

describe('isCrossSiteWrite (CSRF, M-3 da Etapa 2)', () => {
  it('recusa escrita vinda de outro site', () => {
    expect(isCrossSiteWrite('POST', 'https://evil.example', null)).toBe(true);
    expect(isCrossSiteWrite('POST', 'null', null)).toBe(true);
    expect(isCrossSiteWrite('POST', null, 'cross-site')).toBe(true);
    expect(isCrossSiteWrite('PATCH', 'http://localhost.evil.example', 'cross-site')).toBe(true);
  });

  it('aceita a própria origem, leitura e clientes sem Origin', () => {
    expect(isCrossSiteWrite('POST', 'http://127.0.0.1:3000', 'same-origin')).toBe(false);
    expect(isCrossSiteWrite('POST', 'http://localhost:3000', null)).toBe(false);
    expect(isCrossSiteWrite('GET', 'https://evil.example', 'cross-site')).toBe(false);
    expect(isCrossSiteWrite('POST', null, null)).toBe(false);
  });
});
