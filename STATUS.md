# STATUS

**Atualizado em:** 2026-11-22
**Etapa atual:** Etapa 2 — Dados (implementada; aguardando CI no GitHub e aprovação do fechamento)
**Próxima etapa:** Etapa 3 — Volatilidade e eventos (bloqueada até o fechamento da Etapa 2)

## Aprovações

| Documento | Versão | Situação | Data |
|-----------|--------|----------|------|
| BRD | 1.0 | Aprovado | 2026-11-21 |
| PRD | 1.0 | Aprovado | 2026-11-21 |
| Relatório da Etapa 0 ([docs/pesquisa/etapa-0.md](docs/pesquisa/etapa-0.md)) e alterações A-01..A-10 | 1.0 | Aprovado | 2026-11-22 |
| BRD | 1.1 | Aprovado (incorpora A-01..A-10) | 2026-11-22 |
| PRD | 1.1 | Aprovado (incorpora A-01..A-10 e universo inicial) | 2026-11-22 |
| BRD / PRD | 1.2 | Aprovado (liquidez mínima de 20 negócios) | 2026-11-22 |
| Fechamento da Etapa 1 (Fundação): CI verde (run 45054728296) e revisão de segurança com bloqueantes corrigidos | — | Aprovado | 2026-11-22 |

## Feito

- Landing page com a superfície de volatilidade 3D (antes do BRD).
- BRD 1.0 escrito e aprovado.
- Entrevista de arquitetura concluída. As decisões estão no PRD §3 (ADR-01 a ADR-16).
- PRD 1.0 escrito e aprovado.
- Ambiente do projeto criado: `AGENTS.md` (contexto e regras), `CLAUDE.md`, papéis em `.claude/agents/`, `PLANO.md` e este arquivo.
- BRD e PRD atualizados para 1.1 com os resultados da Etapa 0; PLANO ajustado (fixtures na Etapa 1, COTAHIST na Etapa 2).
- **Etapa 0 concluída (2026-11-22):** relatório em `docs/pesquisa/etapa-0.md`; fixtures reais (8,5 MB, com SHA-256), hoje em `services/engine/tests/fixtures/`; scripts exploratórios em `docs/pesquisa/scripts/`.
- **Etapa 1 concluída e aprovada (2026-11-22):**
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
  - **CI no GitHub: verde** nos 6 jobs (commit 7bbdd4d, branch `etapa-1-fundacao`, run 45053794816).
  - **Revisão de segurança (2026-11-22): aprovada com ressalvas**, todas as bloqueantes corrigidas:
    - A-1 (alto, bloqueante) — Next escutava em `0.0.0.0` (padrão do Next 16): `dev`/`start` agora com `-H 127.0.0.1`, com teste que impede regressão; PRD-NF-01 esclarecido.
    - M-1 — DNS rebinding: `proxy.ts` no Next recusa `Host` não local em `/app` e `/api/engine/*`; o engine recusa `Host`/`X-Forwarded-Host` não local (o rewrite usa `changeOrigin`, então a checagem só no engine não bastava).
    - M-2 (a) — migration `0002`: `TRUNCATE` em `config_versions` também é bloqueado.
    - B-1 — pytest só aceita `TEST_DATABASE_URL` terminado em `_test`. B-3 — compose mantém `${VAR:?}` no engine-api. B-4 — `.dockerignore` com `.env*`.

- **Etapa 2 implementada (2026-11-22), branch `etapa-2-dados`, aguardando aprovação:**
  - Migration `0003`: `underlyings` (universo inicial semeado), `option_series`, `series_adjustments`, `exchange_holidays` (1.147 dias: lista nacional + regras B3; 2025–2026 confirmados), `risk_free_rates`, `corporate_actions`, `raw_files`, `trades` (particionada por mês, chave com o instrumento primeiro), `daily_bars`, `option_daily_stats`, `collection_runs`, `collection_items` (PRD §6).
  - Fontes isoladas em `data/` (RF-DAD-07): B3 negócios e COTAHIST diário/anual, BCB SGS, Yahoo (httpx). Cliente educado (1 req/s, backoff, UA genérico, só HTTPS para hosts conhecidos, corpo limitado), ZIP seguro, cache bruto por SHA-256 (PRD-NF-02/05, ADR-06).
  - Ingestão idempotente: OHLC oficial, séries pelo ISIN com estilo inferido, ajustes de strike recalculados (com provento oficial implícito para conferir o Yahoo), negócios via COPY com R4 e verificação contra o COTAHIST, Selic em decimal, proventos do Yahoo como estimados (RN-DAD-01..03, RS-02).
  - Coleta sob demanda no worker: planejamento sem agendador, pré-filtro de séries pelo COTAHIST (QA-06) em uma consulta SQL, commit por item, retomada após parada do worker, interrupção após 5 falhas transitórias seguidas, heartbeat do lock (ADR-07, PRD-NF-03/10).
  - API: `/collection/pending`, `/collection/runs`, `/collection/runs/{id}`, `/collection/gaps`, `/underlyings` (GET/POST/PATCH, limite de 10); `/health` com a última coleta e a fonte; contrato 0.2.0.
  - Telas: card de pendências no `/app` e `/app/coleta` (progresso ao vivo, relatório de lacunas por ativo e data).
  - Testes: engine 101 (unit, integração com fixtures reais: R4 = OHLC oficial em 41/41 pares, idempotência, reprocessamento a partir de `data/raw/` com estado idêntico, retomada, equivalência do filtro SQL × regra pura); web 53; Playwright 4 (inclui o **fluxo 1**), numa stack própria com fonte simulada (`docker-compose.e2e.yml`). `next build` ok.
  - Revisão de segurança: **aprovada com ressalvas**. Bloqueantes corrigidos com teste: M-1 (linha sem quebra lida inteira na memória) e M-2 (exceções não classificadas derrubavam a coleta e ecoavam conteúdo no log, B-5 do backlog da Etapa 1). Corrigidos também M-3 (CSRF no POST da coleta: `proxy.ts` e engine recusam escrita de outra origem), M-4 (consultas de dados do usuário por `user_id`), B-1 (temporário do cache com `mkstemp`), B-2 (só stored/deflate), B-3 (`fullmatch` no ticker), B-4 (parser do Yahoo), B-5 (upserts em lotes, sem duplicatas).
  - Revisão de performance: bloqueantes corrigidos: ordem da chave de `trades` (instrumento primeiro; série em 63 pregões 363 ms → 3 ms) e `/collection/pending` (consulta única com filtro no banco; 26 ms após a coleta das fixtures; polling reduzido a 30 s com coleta ativa). Também: partições criadas no planejamento (fora da transação do item), índice do próximo item com `trade_date DESC`, `React.memo` no relatório. Carga inicial estimada em ~5,0 h, como no PRD-NF-04.

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
| 2026-11-22 | **Yahoo por httpx direto na API de gráficos, sem `yfinance`** (decisão do usuário; mesmo cliente, cache e fixtures das outras fontes) | PRD 1.3 §3.1 |
| 2026-11-22 | **IDs de negócio reiniciam a cada pregão**: identidade = (DataNegocio, ID); a R4 e a chave de `trades` usam os dois (PETR4 18/11, ID 353710 em D-1 e no dia) | PRD 1.3 §6 |
| 2026-11-22 | **PRD-QA-02 resolvida**: partição mensal basta; a chave de `trades` começa pelo instrumento | PRD §14 |
| 2026-11-22 | `TipoSessaoPregao = 6`: nas fixtures, 154 negócios entre 19:25 e 19:37 (após o fechamento), preços perto do fechamento: compatível com sessão estendida pós-fechamento; a R4 os exclui e o OHLC confere. Semântica oficial ainda sem documento da B3 | RN-DAD-01 |
| 2026-11-22 | HTTP 404 é falha definitiva só no `rapinegocios` (ticker inexistente); COTAHIST/SGS/Yahoo podem não ter publicado ainda e são tentados de novo | PRD 1.3 §6 |
| 2026-11-22 | Parâmetros da coleta (filtro QA-06 e janelas 63/252 pregões) em `config_versions.params.collection`; a primeira coleta cria a versão inicial | PRD §5.3 |
| 2026-11-22 | E2E numa stack separada (`vollab-e2e`, fonte simulada, hoje = 20/11/2026); o fluxo de coleta se pula contra fonte real | PRD 1.3 §10.3 |
| 2026-11-22 | `GET /underlyings/{t}/series` fica para a Etapa 3, com a tela do ativo | PLANO |
| 2026-11-22 | **Universo inicial: BOVA11, BBAS3, PETR4** (configuração; BRD permite até 10). Carga inicial ≈ 18,0 mil req (~5,0 h, com ≥ 20 negócios); diária ≈ 285 req (~5 min) | PRD-NF-04 |

## Bloqueios e riscos ativos

- Calendário 2027 provisório até a B3 publicar.
- Backlog de segurança (revisão da Etapa 1, não bloqueante):
  - M-2 (b): separar papéis do Postgres (dono das migrations × aplicação sem DDL/UPDATE/DELETE nas tabelas imutáveis) — junto com as decisões gravadas, Etapa 6.
  - B-2: fixar ações do CI por SHA (com Dependabot) e imagens por digest/versão completa (`uv:0.13.9`).
  - ~~B-5~~: resolvido na Etapa 2 (DSN com `SecretStr`; `last_error`, erros de item e logs só com o tipo do erro).
  - B-6: `ENGINE_URL` do rewrite é fixado no `next build` (documentar ou mover para `proxy.ts`).
- Antes de hospedar (ADR-14): autenticação no `proxy.ts`/Route Handlers com lista de rotas permitidas; desligar `/docs` e `/openapi.json`; TLS até banco e engine; CSP, CSRF e rate limit; gerenciador de segredos; rever o que o `/health` expõe.
- `rapinegocios` atrás do Cloudflare: monitorar bloqueios na carga inicial (1 req/s).
- Yahoo bruto × líquido: não confirmável sem dados novos; o Yahoo segue como `estimado` e o ajuste de strike do COTAHIST é a referência oficial (`b3_strike_adjustment`).
- Backlog da revisão de segurança da Etapa 2 (não bloqueante): B-6 (gravar a fonte `live`/`fixtures` em `collection_runs`/`raw_files` e impedir misturar no mesmo banco), B-7 (prazo total de download e pico de memória do COTAHIST anual, ~2× o arquivo), B-8 (corrida no limite de 10 ativos). Ao hospedar: rever o que `/health` e `/collection/pending` expõem.
- Backlog da revisão de performance da Etapa 2 (não bloqueante): `executemany` nos upserts do COTAHIST (compilação do SQLAlchemy domina ~0,6 s por pregão); `r4_mask` calculado duas vezes por arquivo do ativo; evitar a cópia `bytes(body)` no download. Para a Etapa 3: não agregar negócios brutos na requisição (PETR4 em 63 pregões = 4,4 milhões de linhas, ~1,2 s); gravar agregados no worker após a coleta.
- Retenção de `trades` não definida (~8 GB/ano com 3 ativos).

## Próximos passos

1. CI verde no GitHub para a branch `etapa-2-dados` (PR aberto).
2. Aprovação do usuário: fechamento da Etapa 2 e PRD 1.3.
3. Primeira carga real (~5 h, em várias sessões): `npm run engine:up` e **Coletar agora** no painel; acompanhar bloqueios do Cloudflare no relatório de lacunas.
4. Depois da aprovação: liberar a Etapa 3 (Volatilidade e eventos).
