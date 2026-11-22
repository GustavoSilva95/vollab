# STATUS

**Atualizado em:** 2026-11-22
**Etapa atual:** Etapa 1 — Fundação (implementada; fechamento pendente: CI verde no GitHub, revisão de segurança e aprovação)
**Próxima etapa:** Etapa 2 — Dados (bloqueada até o fechamento da Etapa 1)

## Aprovações

| Documento | Versão | Situação | Data |
|-----------|--------|----------|------|
| BRD | 1.0 | Aprovado | 2026-11-21 |
| PRD | 1.0 | Aprovado | 2026-11-21 |
| Relatório da Etapa 0 ([docs/pesquisa/etapa-0.md](docs/pesquisa/etapa-0.md)) e alterações A-01..A-10 | 1.0 | Aprovado | 2026-11-22 |
| BRD | 1.1 | Aprovado (incorpora A-01..A-10) | 2026-11-22 |
| PRD | 1.1 | Aprovado (incorpora A-01..A-10 e universo inicial) | 2026-11-22 |
| BRD / PRD | 1.2 | Aprovado (liquidez mínima de 20 negócios) | 2026-11-22 |

## Feito

- Landing page com a superfície de volatilidade 3D (antes do BRD).
- BRD 1.0 escrito e aprovado.
- Entrevista de arquitetura concluída. As decisões estão no PRD §3 (ADR-01 a ADR-16).
- PRD 1.0 escrito e aprovado.
- Ambiente do projeto criado: `AGENTS.md` (contexto e regras), `CLAUDE.md`, papéis em `.claude/agents/`, `PLANO.md` e este arquivo.
- BRD e PRD atualizados para 1.1 com os resultados da Etapa 0; PLANO ajustado (fixtures na Etapa 1, COTAHIST na Etapa 2).
- **Etapa 0 concluída (2026-11-22):** relatório em `docs/pesquisa/etapa-0.md`; fixtures reais (8,5 MB, com SHA-256), hoje em `services/engine/tests/fixtures/`; scripts exploratórios em `docs/pesquisa/scripts/`.
- **Etapa 1 implementada (2026-11-22):**
  - Monorepo com npm workspaces: `apps/web`, `services/engine`, `packages/api-types`; `data/raw/` no `.gitignore` (ADR-15).
  - Landing migrada para TypeScript (strict), visual e comportamento iguais; mesmas versões de three/fiber/drei/next/react (ADR-01).
  - `/entrar` → 307 para `/app`; `/cadastro` "em breve"; casca do `/app` com navegação (telas futuras desabilitadas, com a etapa) e painel com o estado do engine (ADR-13, PRD §8.1).
  - Rewrites `/api/engine/*` → engine; sem CORS (ADR-09). A landing não carrega código do cockpit (PRD-NF-07, verificado nos chunks).
  - Engine: FastAPI (`/health`, erros RFC 9457), SQLAlchemy 2, Alembic (migration `0001`: `users` com usuário fixo, `config_versions` imutável por trigger, fila `jobs`), worker com `SKIP LOCKED`, backoff e retomada de jobs travados (ADR-03/05/08, PRD §5.3, PRD-NF-03).
  - `docker-compose.yml` (postgres 17, engine-migrate, engine-api, engine-worker; portas só em 127.0.0.1) e `.env.example` (PRD-NF-01/09).
  - Contrato: OpenAPI exportado de forma determinística → Hey API → `packages/api-types` (tipos, Zod, SDK, TanStack Query); `npm run contract:check` (ADR-10).
  - `lib/format` com T-REF-06 (parte web, 25 testes) e regra de lint que proíbe formatação fora dele (PRD-UI-03).
  - CI (`.github/workflows/ci.yml`) com os 6 jobs do PRD §10.4. Reproduzidos localmente a partir de `npm ci`: todos verdes (web: 28 testes; engine: 21 testes, ruff, mypy estrito; e2e: 3 testes; contrato determinístico). **Ainda não rodou no GitHub.**
  - Fixtures movidas para `services/engine/tests/fixtures/` (SHA-256 conferidos por teste); `feriados.csv` em `services/engine/src/vollab/db/seed/`.

## Decisões registradas

| Data | Decisão | Onde |
|------|---------|------|
| 2026-11-21 | Stack: TS (web) + Python/FastAPI (engine) + Postgres/Docker; só o engine acessa o banco | PRD §3 |
| 2026-11-21 | Coleta sob demanda com recuperação de pregões pendentes, sem agendador | ADR-07 |
| 2026-11-21 | `/entrar` leva ao cockpit; `/cadastro` mostra "em breve"; modelo de dados com `user_id` | ADR-13 |
| 2026-11-21 | Testes de referência obrigatórios no lugar de cobertura percentual; CI falha com drift do contrato | PRD §10 |
| 2026-11-22 | PM-02 validada: o endpoint aceita tickers de opção | etapa-0 §2 |
| 2026-11-22 | QA-13: regra R4 (sessão 1, `DataNegocio = DataReferencia`, remove IDs cancelados, ordena por ID) | BRD RN-DAD-01 |
| 2026-11-22 | QA-01: COTAHIST como cadastro; ativo-objeto pelo ISIN; série = (código, vencimento); estilo inferido | BRD RN-DAD-02 |
| 2026-11-22 | Estilo de exercício pelo sufixo `E` **confirmado** contra o Cadastro de Instrumentos oficial (14.003/14.003; universo inicial 2.307/2.307 em estilo, ativo, tipo, strike e vencimento) | etapa-0 §4 |
| 2026-11-22 | COTAHIST como segunda fonte B3 (OHLC oficial, cadastro, pré-filtro da coleta) | BRD §8, PRD §6 |
| 2026-11-22 | QA-02: feriados pela página da B3 + lista nacional 2001–2078 fornecida pelo usuário, complementada por 20/11, 24/12 e 31/12 (conferida 100% com 2025–2026) | BRD §8, PRD §6.1 |
| 2026-11-22 | QA-04: IV de referência = mediana das IVs sincronizadas na última hora (mín. 3) | BRD RN-VOL-06 |
| 2026-11-22 | QA-05: janela de sincronização de 10 s | BRD RN-VOL-03 |
| 2026-11-22 | QA-06: padrão ≥ 10 negócios, K/S 0,9–1,1, 2 vencimentos mensais, semanais desligadas | BRD §15 |
| 2026-11-22 | **QA-06 revista pelo usuário: mínimo de 20 negócios no dia** (−5% de séries em relação a 10; 99,8% dos negócios retidos). Avaliados também 21 e 51 (51 cortava ~10% das séries ATM do 2º vencimento). BRD e PRD → 1.2 | BRD §15, PRD-NF-04 |
| 2026-11-22 | RS-02: Yahoo só para histórico, conferido pelo ajuste de strike; proventos futuros manuais | BRD §8 |
| 2026-11-22 | **PRD-QA-01 resolvida:** Hey API (`@hey-api/openapi-ts` 0.99) adotado; gera tipos, Zod, SDK com validação de resposta e `queryOptions`; saída determinística. Plano B descartado | PRD §14 |
| 2026-11-22 | Nomes físicos da fundação: `users` (usuário fixo `00000000-0000-0000-0000-000000000001`), `config_versions` (UPDATE/DELETE bloqueados por trigger), `jobs` (status `queued/running/succeeded/failed`, 3 tentativas, backoff 30 s·2ⁿ, lock antigo > 600 s volta à fila) | PRD §6 |
| 2026-11-22 | TypeScript fixado em 6.0 (o 7 não expõe a API do compilador, usada pelo typescript-eslint e pelo Hey API) | — |
| 2026-11-22 | A tabela `exchange_holidays` e a carga do `feriados.csv` entram na Etapa 2, junto com o adaptador de feriados; na Etapa 1 o arquivo só foi movido para o seed do engine | PLANO |
| 2026-11-22 | `js-yaml` forçado para ≥ 4.3.2 via `overrides` (o Hey API fixa 4.2.0, com 3 alertas altos de CPU); `npm audit` zerado | — |
| 2026-11-22 | **Universo inicial: BOVA11, BBAS3, PETR4** (configuração; BRD permite até 10). Carga inicial ≈ 18,0 mil req (~5,0 h, com ≥ 20 negócios); diária ≈ 285 req (~5 min) | PRD-NF-04 |

## Bloqueios e riscos ativos

- Calendário 2027 provisório até a B3 publicar.
- CI ainda não executado no GitHub (falta push). O `contract-drift` só passa com `packages/api-types` commitado.
- Revisão de segurança da Etapa 1 (bind local, segredos, CORS) pendente — exigida pelo PLANO para fechar a etapa.
- `rapinegocios` atrás do Cloudflare: monitorar bloqueios na carga inicial (1 req/s).
- Semântica de `TipoSessaoPregao = 6` e valores do Yahoo (bruto × líquido) a investigar na Etapa 2.

## Próximos passos

1. Commit e push da Etapa 1; confirmar o CI verde no GitHub.
2. Revisão de segurança (`revisor-seguranca`) e correção dos achados.
3. Aprovação do usuário para fechar a Etapa 1 e liberar a Etapa 2 (Dados).
