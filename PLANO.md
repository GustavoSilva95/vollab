# PLANO — Etapas de construção do VolLab (fase 1 do produto)

Fonte: [BRD](docs/BRD.md) → [PRD](docs/PRD.md) → este plano.
Situação atual: [STATUS.md](STATUS.md).

> "Fase 1" e "fase 2" se referem ao **escopo do produto** (BRD). Este plano divide a fase 1 em **etapas** de construção.

## Regras de passagem entre etapas

1. Uma etapa só começa com o **documento da etapa anterior aprovado** pelo usuário. A aprovação fica registrada em `STATUS.md`, com data.
2. Cada etapa fecha com: critérios de saída cumpridos, CI verde, revisões de segurança e de performance feitas quando indicadas, e `STATUS.md` atualizado.
3. Descobertas que mudam escopo **param a etapa**: o BRD e o PRD são atualizados e aprovados antes de seguir.
4. Decisões tomadas durante a etapa (questões QA-xx resolvidas) são registradas em `STATUS.md` e, se forem estruturais, no PRD.

---

## Especificação

| Item | Situação |
|------|----------|
| BRD 1.0 | Aprovado em 2026-11-21 |
| PRD 1.0 | Aprovado em 2026-11-21 |
| Ambiente do projeto (AGENTS.md, papéis, PLANO, STATUS) | Aprovado em 2026-11-21 |

**Saída:** PRD aprovado → libera a Etapa 0.

---

## Etapa 0 — Pesquisa e validação

**Papel principal:** analista (com o desenvolvedor para scripts descartáveis de coleta exploratória).
**Entregáveis**
- `docs/pesquisa/etapa-0.md`, com respostas e evidências para PM-01, PM-02, QA-01, QA-02, QA-04, QA-05, QA-06, QA-13, RS-02 e o volume real de séries (PRD §12).
- Fixtures reais da B3 (CSV/ZIP) salvas para os testes de ingestão.

**Critérios de saída:** todos os critérios da tabela do PRD §12. Se PM-02 falhar → revisar o BRD e o PRD.
**Gate:** relatório da Etapa 0 aprovado. ✅ **Concluída em 2026-11-22** (relatório aprovado; BRD e PRD atualizados para 1.1).

---

## Etapa 1 — Fundação

**Entregáveis**
- Monorepo (`apps/web`, `services/engine`, `packages/api-types`, `data/raw/` no `.gitignore`).
- Fixtures da Etapa 0 movidas de `docs/pesquisa/fixtures/` para `services/engine/tests/fixtures/` (com o `MANIFEST.csv`). A lista de feriados (`fixtures/calendario/feriados.csv`) vai para os dados de carga do engine (seed de `exchange_holidays`), não para os testes.
- Código atual migrado para TypeScript, landing funcionando igual a antes.
- `/entrar` redireciona para `/app`; `/cadastro` mostra "em breve"; casca do `/app` com navegação.
- `docker-compose.yml` com Postgres, engine-api e engine-worker; `.env.example`.
- Engine: FastAPI com `/health`, SQLAlchemy, Alembic, usuário fixo, `config_versions`, fila `jobs`.
- Geração do contrato (resolver PRD-QA-01) e o job `contract-drift`.
- `lib/format` com testes de unidades e escalas (T-REF-06, parte web).
- CI completo (PRD §10.4) com os jobs vazios ou mínimos passando.

**Critérios de saída:** `docker compose up` mais `npm run dev` sobem tudo; CI verde; contrato gerado e versionado.
**Revisões:** segurança (bind local, segredos, CORS).
**Gate:** ✅ **Concluída em 2026-11-22** (CI verde; revisão de segurança aprovada com ressalvas, bloqueantes corrigidos; fechamento aprovado pelo usuário).

---

## Etapa 2 — Dados

**Entregáveis**
- Adaptadores B3 (negócios `rapinegocios`, COTAHIST diário e anual para OHLC oficial, cadastro de séries e pré-filtro de opções; feriados), BCB SGS e Yahoo (proventos), isolados (RF-DAD-07).
- Cache bruto imutável com hash; parsing de CSV e ZIP seguro (PRD-NF-05).
- Coleta sob demanda: `/collection/pending`, execução no worker, progresso, retomada e relatório de lacunas.
- Carga inicial em várias sessões (PRD-NF-04).
- OHLC diário (RN-DAD-01), séries com ajustes por provento (RN-DAD-03).
- Telas `/app` (pendências) e `/app/coleta`.

**Critérios de saída:** testes de ingestão com fixtures reais; idempotência comprovada; Playwright, fluxo 1.
**Revisões:** segurança (entrada não confiável, ZIP) e performance (inserção em lote, índices, particionamento — PRD-QA-02).
**Gate:** implementada em 2026-11-22 (branch `etapa-2-dados`); revisões feitas e bloqueantes corrigidos; CI verde (run 45062752607). ✅ **Concluída em 2026-11-22** (fechamento e PRD 1.3 aprovados pelo usuário).

---

## Etapa 3 — Volatilidade e eventos

**Entregáveis**
- `quant/pricing` (BS europeu com dividendos discretos), `quant/vol` (close-to-close com média zero e divisor *n* como padrão e a forma com média subtraída para comparação, correção de viés por `bias_b_zero_mean`; Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang, RV intradiária de 5 min com overnight; IV com sincronização temporal) — BRD 1.3 RF-VOL-01, RN-VOL-07..09; PRD 1.5 §5.5. Fórmulas conforme `docs/referencia/volatility-trading.md` (nunca a forma impressa listada na Errata).
- Barras de 5 min (`intraday_bars`) e RV por estimador e janela (`realized_vols`) calculadas **no worker após a coleta**; retornos ajustados por proventos.
- `GET /underlyings/{t}/series` (adiado da Etapa 2).
- Smile, estrutura a termo, IV de prazo constante (QA-03; indisponível sem dois vencimentos).
- Calendário de eventos (CRUD) e salto de evento (RN-EVT-01..03).
- Tela `/app/ativos/[ticker]` (inclui a comparação dos estimadores lado a lado, com a hipótese de cada um) e `/app/eventos`, com Plotly (pacote parcial, bandas e lacunas).

**Critérios de saída:** T-REF-01 a T-REF-05 passando (T-REF-05 com os 6 estimadores).
**Revisões:** performance (cálculo de IV vetorizado; barras de 5 min e RV no worker; bundle do Plotly).
**Gate:** implementada em 2026-11-22 (branch `etapa-3-volatilidade-eventos`); T-REF-01..05 passando; revisão de performance sem bloqueantes (importantes corrigidos). ✅ **Concluída em 2026-11-23** (fechamento e PRD 1.6 aprovados pelo usuário).

---

## Etapa 4 — Previsão de RV e avaliação de modelos

**Entregáveis:** EWMA, combinação de estimadores e GARCH(1,1) explícito (BRD 1.3 RF-PRV-02); horizonte igual à vida da opção; avaliação com janelas não sobrepostas contra os baselines; método dos intervalos (QA-07, QA-08); tela `/app/modelos`.
**Critérios de saída:** T-REF-09; "dados insuficientes" funcionando; CS-03 verificável.
**Gate:** implementada em 2026-11-23 (branch `etapa-4-previsao`, PRD 1.7); T-REF-09 passando; revisão de performance sem bloqueantes (M-2 e M-3 corrigidos). ✅ **Concluída em 2026-11-23** (merge direto na `main`, decisão do usuário).

---

## Etapa 5 — Custos, edge e ranking

**Entregáveis:** custos configuráveis e spread estimado (RN-CST-01..03); prêmio de vol absoluto e edge relativo com intervalo, descontados do spread normal (RN-EDG-01/02/07, PRD §5.6; resolver QA-14); semáforo de 3 estados (RN-EDG-03..06); ranking (`/app/ranking`); tela de configurações versionadas; valores padrão definidos com o usuário (QA-11).
**Critérios de saída:** testes do semáforo nos três estados e nos limites; rótulo "não calibrado".
**Gate:** implementada em 2026-11-23 (branch `etapa-5-custos-edge`, BRD 1.5, PRD 1.8.1); testes do semáforo nos três estados, nas duas direções e nos limites passando; rótulos "não calibrado" na tela e na API. Revisão de performance sem bloqueantes (I-1 e menores corrigidos); CI verde (runs 45290076552 e 45291444806). ✅ **Concluída em 2026-11-23** (fechamento aprovado pelo usuário; mesclada na `main`).

---

## Etapa 6 — Simulador e dimensionamento

**Entregáveis:** simulação das 3 estruturas com séries reais e preços manuais; distribuição de P&L por bootstrap com a regra de hedge (QA-10); P&L esperado líquido; Kelly fracionado e teto (QA-09); registro da entrada com retrato da decisão.
*(BRD 1.6 / PRD 1.9, aprovados em 2026-11-23)* 5 estruturas (as 3 vendidas + straddle e strangle comprados); bootstrap reescalado para σ̂ com banda de delta; perda máxima = maior entre ES 99% e stress; `positions`, `position_entries` (entrada) e `manual_inputs` imutáveis; papéis do Postgres separados (backlog M-2 b); tela `/app/simulador`.
**Gate de início:** ✅ BRD 1.6 e PRD 1.9 aprovados pelo usuário (2026-11-23).
**Gate:** implementada em 2026-11-23 (branch `etapa-6-simulador-dimensionamento`); T-REF-07 passando; Playwright fluxo 2 passando; CS-01 por construção (entrada sem semáforo recusada com 422); 10.000 caminhos em ~0,1 s (~1 s no pior vencimento). CI verde nos 6 jobs (run 45309490121); revisão de performance sem bloqueantes (I-1, I-2 e M-2 corrigidos). Aguarda aprovação do fechamento.
**Critérios de saída:** T-REF-07; Playwright, fluxo 2; CS-01 garantido por construção (não existe entrada sem semáforo).
**Revisões:** performance (10.000 caminhos em < 3 s).

---

## Etapa 7 — Diário, carteira e risco

**Entregáveis:** lançamentos tipados (hedge, ajuste, exercício, designação, saída, rolagem); validações de consistência (RS-06); marcação D-1; atribuição por Greek com resíduo; Greeks agregados; exposição por vencimento; stress (QA-12) e limites.
**Critérios de saída:** T-REF-08; Playwright, fluxo 3; CS-04 medido.

---

## Etapa 8 — Gestão da operação

**Entregáveis:** alertas de hedge (banda e tempo), saída (edge acabou e opcionais), rolagem só com edge líquido, limites e proventos com posição aberta (RS-07); painel de alertas.
**Critérios de saída:** testes de cada regra nos limites; alertas gravam `config_version_id`.

---

## Etapa 9 — Performance e endurecimento

**Entregáveis:** previsto × realizado nos dois níveis; análise agregada; relatório líquido de custos e de IR; aviso do N = 20; backup e restauração testados (PRD-NF-08); revisão final de segurança e de performance.
**Critérios de saída:** todos os CS do BRD verificáveis na interface; CI verde; documentação de uso local no README.
