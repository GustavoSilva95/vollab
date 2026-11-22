import type { NextConfig } from 'next';

/**
 * URL interna do engine (PRD ADR-09). O navegador nunca a vê: ele chama
 * `/api/engine/*` na mesma origem e o Next encaminha para cá.
 */
const ENGINE_URL = (process.env.ENGINE_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '');

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // O contrato gerado é publicado como fonte TypeScript (packages/api-types).
  transpilePackages: ['@vollab/api-types'],
  async rewrites() {
    return [{ source: '/api/engine/:path*', destination: `${ENGINE_URL}/:path*` }];
  },
};

export default nextConfig;
