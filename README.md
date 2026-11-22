<img src="apps/web/public/logo/logo-com-frase-fundo-escuro.svg" alt="logo-fundo-escuro" width="500"/>

Cockpit de decisão para traders de volatilidade em opções na B3. Escopo em [`docs/BRD.md`](docs/BRD.md) e [`docs/PRD.md`](docs/PRD.md); andamento em [`STATUS.md`](STATUS.md).

## Estrutura

| Pasta | Conteúdo |
|-------|----------|
| `apps/web` | Next.js 16 (TypeScript): landing e cockpit (`/app`) |
| `services/engine` | Python 3.13 (uv): API FastAPI, worker, motor quantitativo, migrations |
| `packages/api-types` | Contrato **gerado** do OpenAPI do engine (não editar `src/generated` à mão) |
| `data/raw/` | Cache bruto da coleta (fora do git) |

## Rodar localmente

Pré-requisitos: Node 24 (`.nvmrc`), [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env        # troque a senha do Postgres
npm install
npm run engine:up           # Postgres + migrations + engine-api + engine-worker (só em 127.0.0.1)
npm run dev                 # http://localhost:3000 — /entrar leva ao cockpit
```

`npm run engine:down` para o engine. Os dados do Postgres ficam no volume `vollab_pgdata`.

## Verificações (as mesmas do CI)

```bash
npm run typecheck && npm run lint && npm test          # web
npm run build && npm run e2e                           # Playwright (engine no ar)
npm run contract:check                                 # contrato em dia com o OpenAPI

cd services/engine
uv run ruff check . && uv run ruff format --check . && uv run mypy
TEST_DATABASE_URL=... uv run pytest                    # integração usa o banco vollab_test do compose
```

## Contrato entre web e engine

Ao mudar um schema Pydantic ou uma rota, rode `npm run contract:generate` e faça commit de `packages/api-types` junto. O job `contract-drift` do CI falha se o gerado divergir do versionado (ADR-10).
