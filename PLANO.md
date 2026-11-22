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
**Gate:** relatório da Etapa 0 aprovado.

---

## Etapa 1 — Fundação

**Entregáveis**
- Monorepo (`apps/web`, `services/engine`, `packages/api-types`, `data/raw/` no `.gitignore`).
- Código atual migrado para TypeScript, landing funcionando igual a antes.
- `/entrar` redireciona para `/app`; `/cadastro` mostra "em breve"; casca do `/app` com navegação.
- `docker-compose.yml` com Postgres, engine-api e engine-worker; `.env.example`.
- Engine: FastAPI com `/health`, SQLAlchemy, Alembic, usuário fixo, `config_versions`, fila `jobs`.
- Geração do contrato (resolver PRD-QA-01) e o job `contract-drift`.
- `lib/format` com testes de unidades e escalas (T-REF-06, parte web).
- CI completo (PRD §10.4) com os jobs vazios ou mínimos passando.

**Critérios de saída:** `docker compose up` mais `npm run dev` sobem tudo; CI verde; contrato gerado e versionado.
**Revisões:** segurança (bind local, segredos, CORS).

---

## Etapa 2 — Dados

**Entregáveis**
- Adaptadores B3 (negócios, cadastro de séries, feriados), BCB SGS e Yahoo (proventos), isolados (RF-DAD-07).
- Cache bruto imutável com hash; parsing de CSV e ZIP seguro (PRD-NF-05).
- Coleta sob demanda: `/collection/pending`, execução no worker, progresso, retomada e relatório de lacunas.
- Carga inicial em várias sessões (PRD-NF-04).
- OHLC diário (RN-DAD-01), séries com ajustes por provento (RN-DAD-03).
- Telas `/app` (pendências) e `/app/coleta`.

**Critérios de saída:** testes de ingestão com fixtures reais; idempotência comprovada; Playwright, fluxo 1.
**Revisões:** segurança (entrada não confiável, ZIP) e performance (inserção em lote, índices, particionamento — PRD-QA-02).

---

## Etapa 3 — Volatilidade e eventos

**Entregáveis**
- `quant/pricing` (BS europeu com dividendos discretos), `quant/vol` (C2C, Yang-Zhang, IV com sincronização temporal).
- Smile, estrutura a termo, IV de prazo constante (QA-03; indisponível sem dois vencimentos).
- Calendário de eventos (CRUD) e salto de evento (RN-EVT-01..03).
- Tela `/app/ativos/[ticker]` e `/app/eventos`, com Plotly (pacote parcial, bandas e lacunas).

**Critérios de saída:** T-REF-01 a T-REF-05 passando.
**Revisões:** performance (cálculo de IV vetorizado; bundle do Plotly).

---

## Etapa 4 — Previsão de RV e avaliação de modelos

**Entregáveis:** EWMA e combinação de estimadores (GARCH como candidato); horizonte igual à vida da opção; avaliação com janelas não sobrepostas contra os baselines; método dos intervalos (QA-07, QA-08); tela `/app/modelos`.
**Critérios de saída:** T-REF-09; "dados insuficientes" funcionando; CS-03 verificável.

---

## Etapa 5 — Custos, edge e ranking

**Entregáveis:** custos configuráveis e spread estimado (RN-CST-01..03); prêmio de vol com intervalo; semáforo de 3 estados (RN-EDG-01..04); ranking (`/app/ranking`); tela de configurações versionadas; valores padrão definidos com o usuário (QA-11).
**Critérios de saída:** testes do semáforo nos três estados e nos limites; rótulo "não calibrado".

---

## Etapa 6 — Simulador e dimensionamento

**Entregáveis:** simulação das 3 estruturas com séries reais e preços manuais; distribuição de P&L por bootstrap com a regra de hedge (QA-10); P&L esperado líquido; Kelly fracionado e teto (QA-09); registro da entrada com retrato da decisão.
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
