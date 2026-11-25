# PRD — Documento de Requisitos de Produto

**Projeto:** VolLab — cockpit de decisão para traders de volatilidade em opções
**Base:** [BRD 1.8 — Fase 1](./BRD.md) (aprovado em 2026-11-24)
**Referência técnica de fórmulas:** [`referencia/volatility-trading.md`](./referencia/volatility-trading.md) — sempre a forma corrigida; nunca a forma impressa no livro de fórmula listada na Errata (§2 da referência)
**Versão:** 1.11
**Data:** 2026-11-24
**Status:** Aprovado (1.11, 2026-11-24)

> **Histórico:** 1.0 (2026-11-21) aprovado. 1.1 (2026-11-22) incorpora os resultados da Etapa 0 ([relatório](./pesquisa/etapa-0.md), alterações A-01..A-10): adaptador COTAHIST, regra R4, IV de referência, filtros de liquidez padrão, feriados com fonte/confirmação, volume de carga revisado e universo inicial de 3 ativos. 1.2 (2026-11-22): filtro de liquidez padrão de ≥ 20 negócios (QA-06) e PRD-NF-04 recalculado. 1.3 (2026-11-22, Etapa 2, aprovado): proventos do Yahoo por httpx na API de gráficos, sem `yfinance` (decisão do usuário); nomes físicos das tabelas de dados confirmados (§6); stack separada do E2E com fonte simulada (§10.3). 1.4 (2026-11-22, aprovado): estimadores de RV do BRD 1.3 (§5.5, §6.2 `intraday_bars` e `realized_vols`, T-REF-05 ampliado) e GARCH(1,1) explícito (§9). 1.5 (2026-11-22, decisão do usuário): referência técnica de fórmulas com Errata; close-to-close padrão com **média zero e divisor n** (eq. 2.1b), forma com média subtraída e *n* − 1 mantida como opção de comparação, correção de viés com `bias_b_zero_mean` (§5.5); prêmio absoluto, edge relativo e spread normal (§5.6, BRD RN-EDG-01/02/07); renumeração RN-EDG-03..06. 1.6 (2026-11-23, Etapa 3, aprovado): detalhes físicos e de método da volatilidade — `intraday_sessions` e `constant_maturity_vols` (§6.2), salto de evento e IV ex-evento calculados na leitura em vez de `event_jumps` (§6.4), `corporate_actions.event_id`, endpoints `/summary` e `/prices` e a lista `/app/ativos` (§7, §8.1), métodos da §5.5.1; nenhuma mudança de escopo do BRD. 1.7 (2026-11-23, Etapa 4, aprovado): métodos de previsão e avaliação (§5.7) com as decisões do usuário — histórico diário mantido em 1 ano (BRD inalterado), intervalo empírico com fallback χ² (QA-07), combinação por média simples sem Parkinson e Garman-Klass, modelo do edge escolhido pelo usuário; amostras mínimas (QA-08); `forecast_evaluation_points` (§6.4); `/models/evaluation/points` e `PUT /models/selection` (§7); T-REF-09 detalhado (§10.2). 1.8 (2026-11-23, Etapa 5, aprovado): métodos de custos, spread normal, edge, semáforo nas duas direções e ranking (§5.6.1, QA-14, QA-11 parcial); `option_spread_estimates` (§6.2); `/ranking` e `/config` detalhados (§7); telas `/app/ranking` e `/app/configuracoes` (§8.1); testes da Etapa 5 (§10.2). 1.8.1 (2026-11-23, decisão do usuário durante a Etapa 5): o spread de fechamento do COTAHIST sai do custo conservador e fica só como conferência — nas fixtures as ofertas após o fechamento vinham ~10× o spread dos negócios (PETR4 ATM 19/11: 15,7% × 1,26%). 1.9 (2026-11-23, Etapa 6, aprovado): métodos do simulador e do dimensionamento (§5.8) com as decisões do usuário — bootstrap reescalado para σ̂ (QA-10), perda máxima = maior entre ES 99% e stress (QA-09), estruturas compradas (BRD 1.6), banda de delta na simulação (QA-11 parcial); blocos `simulation` e `sizing` (§5.3); retrato da decisão detalhado (§5.4); `positions`, `position_entries` e `manual_inputs` imutáveis e papéis do Postgres (§6.5); `/simulations`, `/sizing` e `/positions` detalhados (§7); tela `/app/simulador` (§8.1); testes da Etapa 6 e T-REF-07 detalhado (§10.2). 1.10 (2026-11-24, Etapa 7, aprovado): métodos do diário, da marcação D-1, da atribuição, da carteira, do stress, do cenário de crise (QA-12) e dos limites (§5.9) com as decisões do usuário; blocos `journal` e `risk` (§5.3); `daily_marks`, `pnl_attribution`, `crisis_measurements` e colunas novas em `positions`/`position_entries` (§6.5); rotas de lançamentos, carteira, stress, limites e crise (§7); telas `/app/diario`, `/app/operacoes/[id]` e `/app/carteira` (§8.1); T-REF-08 detalhado, testes da Etapa 7 e fluxo 3 com o indicador de banda (alerta persistente na Etapa 8) (§10). 1.11 (2026-11-24, Etapa 8, aprovado): métodos da gestão da operação (§5.10) com as decisões do usuário (QA-11 resolvida); bloco `management` (§5.3); tabela `alerts` e job `alerts_evaluate` (§6.5); `/alerts` detalhado e edge da posição em `GET /positions/{id}` (§7); painel, operação, simulador com rolagem e configurações (§8.1); testes da Etapa 8 e fluxo 3 com o alerta persistente (§10).

---

## 1. Objetivo deste documento

O BRD define **o quê** e **por quê**. Este PRD define **como** o produto da fase 1 será construído: arquitetura, stack, modelo de dados, contrato entre front e motor, telas, requisitos não funcionais, estratégia de testes e ordem de entrega.

Regras de uso:

- Todo requisito aqui é rastreável a um ID do BRD (RF-, RN-, CS-, QA-…). Requisitos novos, exclusivos deste PRD, usam o prefixo **PRD-**.
- Mudança de escopo exige atualizar o BRD primeiro e depois este PRD.
- Decisões de arquitetura ficam registradas na §3 (ADRs). Uma ADR só muda com nova versão deste documento.

---

## 2. Visão geral da arquitetura

```
┌──────────────────────────── máquina do usuário (local) ─────────────────────────────┐
│                                                                                     │
│  Navegador                                                                          │
│     │                                                                               │
│     ▼                                                                               │
│  apps/web — Next.js 16 (TypeScript)                                                 │
│     • landing (/), cockpit (/app/...)                                               │
│     • Server Components: casca e telas de leitura                                   │
│     • Client Components + TanStack Query: telas interativas                         │
│     • rewrites: /api/engine/*  ──────────────┐                                      │
│                                              ▼                                      │
│  services/engine — Python 3.13 (docker compose)                                     │
│     ┌───────────────────────┐        ┌─────────────────────────────┐                │
│     │ api   (FastAPI)       │        │ worker  (mesmo código)       │                │
│     │ • regras de negócio   │        │ • execução de coletas        │                │
│     │ • motor quantitativo  │        │ • recálculos pós-coleta      │                │
│     │ • única porta ao banco│        │ • fila em tabela (Postgres)  │                │
│     └──────────┬────────────┘        └──────────────┬──────────────┘                │
│                │                                    │                               │
│                ▼                                    ▼                               │
│        PostgreSQL 17 (docker)              data/raw/ (cache imutável CSV/ZIP)       │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
                 │ saída de rede apenas do engine/worker
                 ▼
   B3 (rapinegocios + COTAHIST) · Banco Central SGS (Selic) · Yahoo Finance (proventos)
```

Princípios de arquitetura:

1. **O engine é a única fonte de verdade.** O Next.js não acessa o banco, não calcula edge, Greeks ou tamanho de posição. Ele apenas apresenta e coleta dados.
2. **As fontes de dados ficam atrás de adaptadores** (RF-DAD-07). Trocar a B3 por outra fonte não toca regras de negócio.
3. **Tudo o que foi baixado fica preservado** em `data/raw/` antes de qualquer interpretação (RF-DAD-04).
4. **Decisões são reproduzíveis.** Toda decisão gravada guarda as entradas, a versão da configuração, o modelo de RV e a versão do engine.

---

## 3. Decisões de arquitetura (ADRs)

| ID | Decisão | Motivo | Alternativa descartada |
|----|---------|--------|------------------------|
| ADR-01 | **TypeScript** no front, com migração do código atual (JS) para TS. | Muitas grandezas fáceis de confundir (vol decimal × %, dias úteis × corridos, manual × D-1). | Manter JS. |
| ADR-02 | **Motor quantitativo e coleta em Python 3.13** (numpy, pandas, scipy, `arch`). | Ecossistema numérico maduro; GARCH e estatística prontos. | Tudo em TS dentro do Next.js. |
| ADR-03 | **FastAPI + Pydantic v2**, dependências com **uv**. | Contrato OpenAPI gerado do código; validação forte; leve para rodar localmente. | Flask, Django. |
| ADR-04 | **Somente o engine acessa o banco.** O Next.js chama a API para leitura e escrita, inclusive CRUD. | Regras e retrato da decisão (RN-EDG-06, §7.11 do BRD) num lugar só; schema em uma linguagem só. | Acesso dividido com ORM TS. |
| ADR-05 | **PostgreSQL 17 via Docker**, com SQLAlchemy 2 e Alembic para migrations. | Robusto, aceita API e worker em paralelo, migração direta para a nuvem. | SQLite. |
| ADR-06 | **Cache bruto imutável em disco** (`data/raw/`, fora do git), indexado no banco por hash. | Preservar o histórico se a fonte mudar (RS-01); reprocessar sem baixar de novo. | Guardar só dados tratados. |
| ADR-07 | **Coleta sob demanda, sem agendador.** Ao abrir o cockpit, o engine detecta os pregões pendentes e o usuário dispara a coleta. A coleta é retomável. | Corresponde ao uso real (o Mac nem sempre está ligado); menos peças. | APScheduler, cron. |
| ADR-08 | **Worker separado com fila em tabela Postgres** (`SELECT … FOR UPDATE SKIP LOCKED`). | A coleta sobrevive a reinício da API e mostra progresso; sem Redis ou Celery. | `BackgroundTasks` do FastAPI (não durável); Celery. |
| ADR-09 | **O navegador fala com o engine via `rewrites` do Next.js** (`/api/engine/:path*` → `http://127.0.0.1:8000/:path*`). Server Components chamam o engine diretamente pela URL interna. | Mesma origem, sem CORS; o engine não é exposto ao navegador. É a recomendação do Next 16 para encaminhar a outro backend. Quando houver autenticação, troca-se por Route Handlers ou `proxy.ts`. | Navegador chamando o engine direto (exige CORS e expõe a porta); Route Handler para cada endpoint (repetitivo agora). |
| ADR-10 | **Contrato gerado do OpenAPI**: tipos TS, esquemas Zod e hooks do TanStack Query gerados em `packages/api-types` e **versionados**. O CI falha se o gerado divergir do versionado. | O Pydantic é a autoridade; o front nunca escreve tipos de API à mão. | Tipos escritos à mão. |
| ADR-11 | **Interface:** CSS Modules e tokens atuais, Radix UI, TanStack Table, React Hook Form com Zod, TanStack Query. | Identidade visual única com a landing; tabelas densas; formulários validados. | Tailwind com shadcn/ui. |
| ADR-12 | **Gráficos com Plotly.js**, carregado dinamicamente (`ssr: false`) a partir de um **pacote parcial**. | Feito para gráficos quantitativos; o mesmo visual em notebooks Python. | ECharts, Recharts. |
| ADR-13 | **Sem autenticação na fase 1**, mas com **modelo de dados multiusuário** (`user_id` nas tabelas do usuário, com um usuário fixo criado na carga inicial). `/entrar` leva ao cockpit e `/cadastro` mostra "em breve". | Custa pouco agora e evita migração na fase de convites. | Implementar login agora (fora do escopo). |
| ADR-14 | **Hospedagem adiada.** Tudo containerizado e configurado por variáveis de ambiente. | Manter portabilidade sem escolher fornecedor. | — |
| ADR-15 | **Monorepo** (§4). | Contrato, front e motor evoluem juntos, num único CI. | Repositórios separados. |
| ADR-16 | **Identificadores de código em inglês; interface, documentação e commits em português.** Campos brutos da B3 mantêm o nome original apenas na camada de ingestão. | Padrão das bibliotecas; o domínio aparece em português para o usuário. | Código em português. |

### 3.1 Bibliotecas principais

| Camada | Bibliotecas |
|--------|-------------|
| Engine | FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, Alembic, psycopg 3, httpx, numpy, pandas, scipy, arch, structlog. **Yahoo:** httpx direto na API de gráficos (`/v8/finance/chart`, o mesmo backend do yfinance), atrás do mesmo cliente educado, cache bruto e fixtures das outras fontes; `yfinance` não é usado (decisão de 2026-11-22). |
| Qualidade Python | pytest, hypothesis, ruff, mypy (modo estrito no pacote `quant`) |
| Web | Next.js 16, React 19, TypeScript, Radix UI, TanStack Table, TanStack Query, React Hook Form, Zod, Plotly.js (pacote parcial) |
| Geração do contrato | Hey API (`@hey-api/openapi-ts`) com plugins de tipos, Zod e TanStack Query. **Validar na Etapa 1**; plano B: `openapi-typescript` mais esquemas Zod escritos à mão para os formulários. |
| Qualidade web | ESLint, `tsc --noEmit`, Vitest, Testing Library, Playwright |
| Infra | Docker Compose, GitHub Actions; Node 24 (`.nvmrc`), Python 3.13 |

---

## 4. Estrutura do repositório

```
apps/web/              Next.js (TS). A landing e os componentes atuais migram para cá.
  app/                 rotas (landing, /entrar, /cadastro, /app/...)
  components/          UI (inclui background 3D atual)
  lib/format/          módulo ÚNICO de formatação de unidades (PRD-UI-03)
  lib/charts/          wrapper do Plotly (carregamento dinâmico, pacote parcial)
services/engine/       Python (uv)
  src/vollab/api/      rotas FastAPI e schemas Pydantic
  src/vollab/quant/    motor puro (sem I/O): pricing, vol, previsão, edge, sizing, risco, atribuição
  src/vollab/data/     adaptadores de fonte (b3_trades, b3_cotahist, bcb, yahoo), parsing, cache bruto
  src/vollab/jobs/     worker e fila
  src/vollab/db/       modelos SQLAlchemy e migrations Alembic
  tests/               unit, reference, property, integration, fixtures/ (ZIPs reais da B3, vindos de docs/pesquisa/fixtures/)
packages/api-types/    código gerado do OpenAPI (versionado)
data/raw/              cache bruto (no .gitignore)
docs/                  BRD, PRD, pesquisa/ (relatórios da Etapa 0)
docker-compose.yml     postgres + engine-api + engine-worker
PLANO.md, STATUS.md    plano de etapas e situação atual
```

O pacote `quant` **não faz I/O**: recebe arrays e parâmetros e devolve resultados. Isso permite testá-lo isoladamente e reaproveitá-lo no backtest da fase 2.

---

## 5. Convenções transversais

### 5.1 Unidades e escalas (RN-PRC-04, RN-VOL-01)

| Grandeza | Representação na API e no banco | Exibição |
|----------|----------------------------------|----------|
| Volatilidade | **decimal anualizado em base 252** (`0.2534`) | `25,34%` |
| Prêmio de vol | decimal, em pontos de vol (`0.031`) | `3,1 pts` |
| Edge relativo e spread normal | decimal adimensional, razão sobre a RV prevista (`0.25`) | `25%` |
| Taxa de juros | decimal anual, capitalização exponencial, base 252 | `% a.a.` |
| Tempo | **anos úteis** = dias úteis / 252; dias sempre com sufixo explícito (`_bd` úteis, `_cd` corridos) | `21 du` |
| Preço e dinheiro | `Decimal` / `NUMERIC(18,6)` em BRL; nunca float no banco | `R$ 1.234,56` |
| Greeks | por unidade do ativo-objeto e por posição; vega por 1 ponto de vol (0,01), theta por dia útil | conforme rótulo |
| Data e hora | `date` para pregões; `timestamptz` com fuso America/Sao_Paulo para negócios | `dd/mm/aaaa` |

Regras:

- **Percentual só existe na camada de exibição.** A conversão acontece **apenas** em `apps/web/lib/format/`.
- Campos ambíguos carregam a unidade no nome (`horizon_bd`, `days_to_expiry_cd`).
- Testes de unidade e escala são obrigatórios (§10.2).

### 5.2 Valor com proveniência (PR-03, PR-05)

Toda estimativa trafega num envelope padrão, nunca como número solto:

```
EstimatedValue {
  value:        number | null
  ci_low:       number | null      // limite inferior do intervalo
  ci_high:      number | null
  ci_level:     number             // ex.: 0.90 (QA-07)
  status:       "ok" | "insufficient_data" | "unavailable"
  origin:       "observed" | "estimated" | "manual" | "approximate"
  as_of:        date               // pregão de referência
  stale:        boolean            // dado mais antigo que o último pregão
  reason:       string | null      // ex.: "sem dois vencimentos ATM" (RN-VOL-05)
  calibrated:   boolean | null     // para limiares e spread normal (RN-EDG-05/07)
}
```

- `status = insufficient_data` → a interface mostra **"dados insuficientes"** e nunca um número (PR-03, RN-PRV-02).
- `origin ≠ observed` → rótulo visível de "estimado", "manual" ou "aproximado" (PR-05, RN-CST-03, RN-SIZ-06, RF-SIM-03).

### 5.3 Configuração versionada (BRD §7.11)

- As configurações são guardadas em `config_versions`, **imutáveis**. Editar cria uma versão nova.
- Toda decisão, operação e alerta grava o `config_version_id` vigente.
- O primeiro valor de cada parâmetro marcado "a definir com o usuário" (QA-11) é preenchido na etapa que o usa e rotulado como "não calibrado". *(1.8)* Etapa 5: limiar de edge, custos e intervalo de hedge do custo (§5.6.1); Etapas 6 e 8: banda de delta, meta de lucro, stop e dias até o vencimento. *(1.9)* Etapa 6: blocos `simulation` (caminhos, semente, amostra, banda de delta da simulação, payoff) e `sizing` (capital, fração de Kelly, teto, stresses, lote), §5.8. *(1.10)* Etapa 7: blocos `journal` (limiares do resíduo) e `risk` (stresses, episódios de crise, limites de carteira), §5.9. *(1.11)* Etapa 8: bloco `management` (intervalo de hedge, prazo, meta, stop, destino da rolagem, antecedência de proventos), §5.10; a banda de hedge reaproveita `simulation.delta_band`.
- *(1.8)* Edição por `POST /config`: o engine valida o snapshot inteiro (Pydantic), grava uma versão nova com nota e devolve o id; versões nunca são alteradas. Parâmetros de coleta e de vol alterados passam a valer no próximo recálculo (o histórico gravado não é refeito em silêncio).

### 5.4 Retrato da decisão (RF-DIA-01, RN-EDG-06)

Ao registrar uma entrada, o engine grava um retrato imutável (JSONB) com: semáforo, prêmio absoluto e edge relativo com intervalos, spread normal usado (e se calibrado), IV, RV prevista, modelo, custos discriminados, distribuição simulada resumida, Kelly, teto e qual dos dois prevaleceu, tamanho sugerido × executado, `config_version_id`, `engine_version` (git sha) e as entradas manuais usadas. *(1.9)* Também: estrutura, pernas (séries, strikes efetivos, IV e preço de cada perna, com a origem), S, *h*, Greeks da posição, resumo da simulação (média, desvio, percentis, ES 99%, P(P&L < 0), nº de caminhos, semente, tamanho da amostra), perda de cada stress, μ e σ² do Kelly, *n*_Kelly, *n*_teto, regra que prevaleceu, capital, margem manual, lotes executados e o `override_reason` quando houver. Os insumos manuais também vão para `manual_inputs`.

### 5.5 Estimadores de volatilidade realizada (RF-VOL-01, RN-VOL-07..09)

Fórmulas conforme a referência técnica (§3 e Errata). Notação por pregão *t*: O, H, L, C oficiais (COTAHIST), C₋₁ = fechamento anterior **ajustado por proventos** (RN-VOL-07); logs naturais. Janela de *n* pregões; variância anualizada × 252 (RN-VOL-01); a vol é a raiz.

| Estimador | Variância diária (média na janela) | Hipóteses / uso |
|-----------|------------------------------------|-----------------|
| Close-to-close (padrão) | **média zero, divisor *n***: (1/*n*)·Σ ln(Cₜ/C₋₁)² (eq. 2.1b) | baseline do RF-PRV-03 (20 pregões) |
| Close-to-close com média subtraída (comparação) | variância amostral de ln(Cₜ/C₋₁) com média subtraída, divisor *n* − 1 (eq. 2.3) | opção configurável; exibida ao lado da padrão |
| Parkinson | ln(H/L)² / (4 ln 2) | drift zero, sem gap de abertura |
| Garman-Klass | ½ ln(H/L)² − (2 ln 2 − 1) ln(C/O)² | drift zero, sem gap de abertura |
| Rogers-Satchell | ln(H/C)·ln(H/O) + ln(L/C)·ln(L/O) | aceita drift; ignora o overnight |
| Yang-Zhang | σ²ₒ + k·σ²ᶜ + (1 − k)·σ²_RS, com σ²ₒ = variância de ln(O/C₋₁), σ²ᶜ = variância de ln(C/O), k = 0,34 / (1,34 + (*n* + 1)/(*n* − 1)) | aceita drift e gap |
| Intradiária (5 min) | Σ ln(Pᵢ/Pᵢ₋₁)² nas barras de 5 min + ln(O/C₋₁)² | RN-VOL-08; só onde há negócios intradiários |

Regras:
- **Close-to-close:** `config_versions.params.vol.close_to_close_mode` = `zero_mean` (padrão) ou `demeaned`. O modo escolhido é o close-to-close "oficial" (baseline, combinação de estimadores); as duas formas são calculadas e gravadas (`close_to_close` e `close_to_close_demeaned`) para comparação na tela do ativo.
- **Correção de viés da vol (desigualdade de Jensen):** a variância de média zero (1/*n*) já é sem viés, e **não** se aplica *n*/(*n* − 1). A vol exibida é corrigida por s / `bias_b_zero_mean(n)` = s / b₀(*n*), com b₀(*n*) = √(2/*n*)·Γ((*n*+1)/2)/Γ(*n*/2). Na forma com média subtraída e *n* − 1, o fator é c₄(*n*) = `bias_b(n)`·√(*n*/(*n* − 1)). **Nunca** usar `bias_b` (definido para 1/*n* com média subtraída) no estimador de média zero. A variância não corrigida é a que alimenta previsão e GARCH.
- **Barras de 5 min** (`intraday_bars`): grade fixa no relógio de Brasília (10:00, 10:05, …), preço da barra = último negócio válido pela R4 dentro dela; barra sem negócio repete o último preço e conta como vazia para a cobertura. O primeiro retorno intradiário parte da abertura oficial; o último termina no fechamento oficial.
- Janelas padrão: **20 e 60 pregões**, configuráveis (`config_versions`). Janela com pregões faltando, incompletos ou sem OHLC → `insufficient_data` com o motivo (PR-03).
- Tudo é calculado **no worker depois da coleta** (PRD-NF-06) e gravado; as telas só leem. Negócios brutos nunca são agregados dentro de uma requisição.
- Saída em `EstimatedValue` (§5.2), `origin = estimated`; o intervalo de confiança segue o método do QA-07 (Etapa 4).

#### 5.5.1 Métodos adotados na Etapa 3 (1.6)

| Tema | Método |
|------|--------|
| Janela | Estrita: os *n* pregões do calendário até a data; qualquer pregão sem OHLC, com OHLC incoerente, sem fechamento anterior ou (intradiária) incompleto → `insufficient_data` com motivo (`missing_days`, `incomplete_sessions`, `non_positive`). |
| Correção de viés | Só no close-to-close (b₀ e c₄). Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang e intradiária são exibidos sem correção (a referência não traz fator fechado). |
| Grade de 5 min | Abertura configurável (10:00); fim = hora cheia do negócio de fechamento (último pelo identificador; 18:05 → 18:00), o que acompanha a mudança de horário da B3 sem configuração. Negócios do leilão de fechamento ficam fora das barras; o último retorno termina no fechamento oficial. |
| Proventos | Por data ex, prioridade `manual` > `b3_strike_adjustment` > `yahoo`. Retorno: Cₜ₋₁ − D (RN-VOL-07). |
| Precificação | Taxa contínua = ln(1 + Selic); prazo = dias úteis até o vencimento / 252; S* = S − VP(proventos com data ex em (hoje, vencimento]); **strike efetivo = K − Σ proventos** (a B3 reduz o strike na data ex, RN-DAD-03), configurável (`vol.implied.dividend_protected_strikes`). IV por Newton protegido por bisseção, vetorizada; fora dos limites de arbitragem → sem número, com o motivo. |
| IV de referência | Mediana na última hora antes do fim da sessão regular (mesma regra da grade), incluindo o leilão de fechamento; abaixo de 3 negócios, o último negócio sincronizado (`low_sample`). |
| ATM | Por vencimento: interpolação linear em ln(K/F) entre o strike líquido imediatamente abaixo e o imediatamente acima do forward F = (S − VP)·(1 + Selic)^t, usando a opção fora do dinheiro de cada strike; exige os dois lados dentro de K/F 0,9–1,1. |
| Prazo constante | Interpolação linear na variância total σ²t entre os vencimentos que cercam o alvo (padrão 21 du, QA-03); sem extrapolação; sem dois vencimentos, exibe a ATM do vencimento mais próximo com o prazo efetivo (RN-VOL-05). |
| Salto de evento | Eq. 5.3 com o 1º vencimento depois do evento e o seguinte (σ₁ ≤ σ₂ → não precificado). Histórico: retornos ajustados nas datas de resultado passadas cadastradas, média de r² menos a variância diária do close-to-close oficial da maior janela. Valor = estrutura a termo, ou o histórico (`approximate`) sem ela. Intervalo provisório até o QA-07: qui-quadrado do histórico, estendido para conter o valor; sem histórico, sem intervalo e com o motivo. Ex-evento: subtrai σ_E² da variância total de cada vencimento posterior ao evento e interpola de novo (RN-EVT-03). |

### 5.6 Prêmio, edge relativo e spread normal (BRD RN-EDG-01/02/07, Etapa 5)

Notação no mesmo horizonte *h*: IV = IV de prazo constante ex-evento (RN-EVT-03), σ̂ = RV prevista (RF-PRV-04), *s* = spread normal relativo do ativo, *c* = custos estimados em pontos de vol (custo em BRL ÷ vega por ponto, versão conservadora, RN-EDG-04).

| Métrica | Fórmula | Uso |
|---------|---------|-----|
| Spread normal *s* (RN-EDG-07) | razão típica (IV − RV realizada)/RV realizada do próprio ativo; método e padrão na QA-14 | descontado das duas métricas abaixo |
| Prêmio de vol (RN-EDG-01), pontos | IV − σ̂·(1 + *s*) | semáforo (RN-EDG-03) contra *c*; P&L esperado ≈ vega por ponto × pontos |
| Edge relativo (RN-EDG-02) | (IV − σ̂)/σ̂ − *s* = prêmio ÷ σ̂ | ranking e alertas |
| Edge relativo líquido | (prêmio − *c*) ÷ σ̂ | ordenação do ranking (RF-RNK-01) e saída (RN-GES-02) |

- O spread normal é definido uma vez, em termos relativos; a forma absoluta é *s*·σ̂. Assim as duas métricas sempre têm o mesmo sinal.
- Sem histórico suficiente, *s* vem de `config_versions` com `calibrated = false` e rótulo "não calibrado"; nunca zero implícito.
- Todas as métricas saem em `EstimatedValue` com intervalo (QA-07), herdado do intervalo de σ̂.

#### 5.6.1 Métodos adotados na Etapa 5 *(1.8)*

Decisões do usuário (2026-11-23): spread normal padrão de **15%** não calibrado, semáforo nas **duas direções**, corretagem padrão de **R$ 0 por ordem**, limiar de **1 ponto de vol**. Tudo configurável (blocos `costs` e `edge` de `config_versions`).

**Insumos no mesmo horizonte *h*** = `vol.constant_maturity_bd` (21 du):

| Insumo | Origem | Sem o insumo |
|--------|--------|--------------|
| IV | IV de prazo constante **ex-evento** no último pregão (§5.5.1, RN-EVT-03) | Fallback "ATM do vencimento mais próximo" (RN-VOL-05): usa o prazo efetivo *h*′ e σ̂ em *h*′ lido do estado (§5.7); todas as métricas saem `approximate`, com o motivo. Sem IV ATM → **indisponível** |
| σ̂ e [σ̂_lo, σ̂_hi] | Modelo escolhido (`forecast.selected_model`) em *h*, com o intervalo da §5.7 | Modelo sem avaliação no ativo e horizonte → **indisponível** (§5.7), sem troca automática |
| *s* | Spread normal (abaixo) | Nunca falta: cai no valor configurado |
| Custos *c* | Abaixo | Sem estimativa de spread das opções ATM em nenhum pregão da janela → **indisponível** |

**Spread normal *s* (RN-EDG-07, QA-14)**
- Pares das **mesmas origens não sobrepostas** da avaliação do baseline `implied` em *h* (§5.7, `forecast_evaluation_points`): xₖ = (IVₖ − RVₖ)/RVₖ, com IVₖ = IV de prazo constante **com** o evento (a RV realizada da janela também inclui o evento) e RVₖ = RV realizada close-to-close de média zero. Origens nos últimos 252 pregões (LC-03).
- *s* = **mediana** dos xₖ; intervalo por bootstrap percentil (mesma semente e nº de reamostragens da §5.7), só para exibição. Com ≥ `forecast.min_evaluation_windows` (8) pares: `calibrated = true`, `origin = estimated`. Abaixo disso: `edge.normal_spread_default` (**0,15**), `calibrated = false`, `origin = manual`, rótulo "não calibrado" com o nº de pares.
- Calculado na leitura (no máximo ~12 pares por ativo).

**Spread das opções (RN-CST-03)** — no worker, dentro do laço por pregão do `vol_recompute` (negócios já lidos; nada na requisição):
- Por série com ≥ `costs.spread_min_trades` (20) negócios válidos pela R4 na sessão regular: dᵢ = |Pᵢ − Pᵢ₋₁| entre negócios consecutivos **com preço diferente** (o vaivém entre compra e venda, critério "execução × negócio anterior" da referência, cap. 6). Spread da série = mediana dos dᵢ, com **piso** = `costs.tick_brl` (R$ 0,01) ou o piso configurado para o ativo e a faixa; relativo = spread ÷ mediana do preço da série no dia.
- **Faixas de moneyness** por K/F (strike efetivo, §5.5.1): `low` < 0,95 ≤ `atm` ≤ 1,05 < `high` (limites em `costs.moneyness_bands`). Por ativo, pregão e faixa grava-se: nº de séries e de negócios, mediana e percentil 75 do spread relativo entre séries, e a mediana do spread relativo de **fechamento** do COTAHIST (melhor venda − melhor compra)/médio, quando as duas pontas existirem.
- Mesmo método para o **ativo-objeto** (faixa `underlying`), usado no custo de hedge.
- Spread usado no edge, janela de `costs.spread_lookback_bd` (5) pregões: **central** = mediana das medianas; **conservador** (RN-EDG-04, o que entra no semáforo) = mediana dos percentis 75. *(1.8.1)* O spread de fechamento do COTAHIST é exibido **só como conferência**, fora do custo: as ofertas após o fechamento vinham velhas ou fora de mercado (PETR4 ATM: 15,7% × 1,26% pelos negócios em 19/11; 12,9% × 0,66% em 18/11). Sempre `origin = estimated`, rótulo "estimativa".

**Custos em pontos de vol (RN-CST-01, RN-EDG-04)** — estrutura de referência: **straddle ATM teórico** (strike = forward) no prazo *h*, precificado por BS à IV. Prêmio P e vega 𝒱 por unidade de vol (decimal), por opção.
- Opções, ida e volta (entrada e saída, duas pernas): custo em R$ por straddle = Σ pernas [spread_rel × Pᵢ (meio spread na entrada + meio na saída) + 2 × `costs.option_fee_rate` × Pᵢ + 2 × `costs.brokerage_rate` × Pᵢ] + 4 × `costs.brokerage_per_order_brl` ÷ `costs.reference_contracts`. *c*_opç = custo ÷ 𝒱_straddle.
- Hedge (Leland, eqs. 6.7–6.8 da referência, a mesma do código de referência `leland_vol`): λ = meio spread relativo do ativo-objeto (conservador) + `costs.underlying_fee_rate`; Δt = `costs.hedge_interval_bd`/252 (base 252, coerente com σ̂); a = (λ/σ̂)·√(8/(πΔt)). Venda: *c*_hedge = σ̂·√(1 + a) − σ̂. Compra: *c*_hedge = σ̂ − σ̂·√(1 − a); com a ≥ 1 o hedge consome todo o edge de compra (compra **sem edge**, com o motivo).
- *c*_venda = *c*_opç + *c*_hedge,venda; *c*_compra = *c*_opç + *c*_hedge,compra. Exibidos discriminados (opções: spread, taxas, corretagem; hedge), em pontos e em R$ por straddle de referência.
- Padrões: `option_fee_rate` **0,00134** (B3, opções de ações, pessoa física: negociação 0,0370% + liquidação 0,0275% + registro 0,0695%), `underlying_fee_rate` **0,0003** (ações à vista), ambos **a conferir na tabela vigente da B3** e rotulados assim na tela de configurações; `brokerage_per_order_brl` **0**, `brokerage_rate` **0**, `reference_contracts` **100**, `hedge_interval_bd` **1**. O IR fica fora (RN-CST-04).

**Prêmio, edge e semáforo (RN-EDG-01..05)**
- Prêmio *p* = IV − σ̂(1 + *s*), intervalo [*p*_lo, *p*_hi] = [IV − σ̂_hi(1 + *s*), IV − σ̂_lo(1 + *s*)] (herdado de σ̂; *s* entra pelo valor pontual). Edge relativo = *p*/σ̂ com intervalo [*p*_lo/σ̂, *p*_hi/σ̂].
- Limiar *L* = `edge.threshold_vol_pts` (**0,01** = 1 ponto), `calibrated = false` ("não calibrado") até a calibração por dados (Etapa 9, RN-EDG-05). Níveis exigidos: N_v = *c*_venda + *L*; N_c = *c*_compra + *L*.
- Estados (comparações **estritas**; empate nunca dá edge líquido):
  - **Edge líquido — venda** se *p*_lo > N_v; **edge líquido — compra** se *p*_hi < −N_c.
  - **Sem edge** se *p*_hi ≤ N_v **e** *p*_lo ≥ −N_c.
  - **Inconclusivo** nos demais casos.
  - **Indisponível** (fora do semáforo, com o motivo) se faltar IV, σ̂ avaliado ou custos.
- Direção da linha = a do estado, ou o sinal de *p* quando não há edge líquido. **Edge relativo líquido** na direção: venda (*p* − *c*_venda)/σ̂; compra (−*p* − *c*_compra)/σ̂. Também o P&L esperado aproximado por straddle de referência = 𝒱_straddle × (|*p*| − *c*) na direção (sem *L*).
- **Ranking (RF-RNK-01):** edge líquido > inconclusivo > sem edge > indisponível; dentro do estado, edge relativo líquido decrescente; desempate pelo ticker.

**Outras colunas do ranking (RF-RNK-02)**, todas calculadas na leitura:
- **IV rank** e percentil da IV de prazo constante (com evento) nos últimos 252 pregões disponíveis; < 60 pregões → `insufficient_data`; rótulo "relativo ao último ano (N pregões)" (RN-VOL-02, LC-03).
- **Skew** = IV(K/F = 0,95) − IV(K/F = 1,05), em pontos, no vencimento da ATM usada, pela interpolação em ln(K/F) das opções OTM (§5.5.1); sem os dois lados → indisponível.
- **Estrutura a termo** = ATM do 2º vencimento − ATM do 1º, em pontos, com os prazos.
- **Eventos próximos** em (último pregão, + *h* du]; **liquidez**: séries que passam o filtro QA-06, negócios e volume financeiro de opções no pregão (`option_daily_stats`).
- O ranking é calculado na leitura (no máximo 10 ativos; insumos já gravados).

### 5.7 Previsão de RV e avaliação de modelos (RF-PRV-01..04, RN-PRV-01/02, Etapa 4) *(1.7)*

Fórmulas conforme a referência técnica (cap. 4: eqs. 4.1, 4.4–4.5, 4.9). Notação: rₜ = ln(Cₜ / (Cₜ₋₁ − D)), retorno diário **ajustado por proventos** (RN-VOL-07), **média zero**; *t* = pregão de origem (fechamento conhecido); *h* = horizonte em dias úteis (`horizon_bd`, RF-PRV-01). A previsão σ̂(*t*, *h*) é a **vol anualizada média esperada nos pregões *t*+1 … *t*+*h***: √(252 · média das variâncias diárias previstas). Só entram dados até *t* (sem olhar à frente). Variâncias **sem** correção de viés (§5.5).

**Modelos (RF-PRV-02)**

| Modelo | Definição | Amostra mínima (QA-08) |
|--------|-----------|------------------------|
| EWMA (`ewma`) | v₍ₜ₊₁₎ = λ·vₜ + (1 − λ)·rₜ² (eq. 4.1), iniciada pela média de r² dos 20 primeiros retornos; previsão **plana**: σ̂ = √(252·v₍ₜ₊₁₎) para qualquer *h* (a EWMA ignora a reversão à média). λ padrão **0,94**, configurável em [0,90; 0,99]. | 60 retornos (peso do início 0,94⁶⁰ ≈ 2%) |
| Combinação de estimadores (`combination`) | Média simples das variâncias diárias de **janela 20** de close-to-close oficial, Yang-Zhang, Rogers-Satchell e intradiária (esta só nos pregões em que estiver disponível); previsão plana. **Parkinson e Garman-Klass ficam fora** (supõem ausência de gap, RN-VOL-09). Os componentes usados são gravados. | close-to-close, Yang-Zhang e Rogers-Satchell disponíveis na data |
| GARCH(1,1) (`garch`) | Biblioteca `arch`: média zero, inovação normal, retornos × 100 (escala numérica), máxima verossimilhança com todos os retornos válidos até *t* (no máximo 1.260). Previsão: E[σ²ₜ₊τ] = V + (α + β)^(τ−1)·(σ²₍ₜ₊₁₎ − V), V = ω/(1 − α − β) — a eq. 4.9 escrita a partir de σ²₍ₜ₊₁₎ = ω + α·rₜ² + β·σ²ₜ, já conhecido em *t* (eqs. 4.4, 4.5 e 4.9); σ̂ = √(252 · média para τ = 1…*h*). Ajustado nas origens da avaliação e no último pregão (não em todo pregão, pelo custo do ajuste). **"Indisponível" com motivo** se não convergir, se ω ≤ 0, α ou β fora de [0, 1) ou α + β ≥ 0,999. Com menos de 1.000 retornos (sempre, com 1 ano de histórico — LC-04), o motivo registra "estimado com *N* retornos; a referência recomenda ≥ 1.000". | 240 retornos |

Para cada pregão e modelo, o worker grava o **estado** (v, ou ω, α, β e σ²₍ₜ₊₁₎, e os componentes da combinação) e as previsões dos horizontes de avaliação. Outros horizontes (o prazo de cada vencimento, RF-PRV-01) são calculados **na leitura** a partir do estado, por fórmula fechada.

**Baselines (RF-PRV-03)** — usados como previsões e avaliados do mesmo jeito:

| Baseline | Previsão em *t* |
|----------|-----------------|
| `rv_c2c_20` | close-to-close oficial de 20 pregões em *t*, sem correção de viés |
| `implied` | IV de prazo constante em *t* (§5.5.1), só quando *h* = `vol.constant_maturity_bd`; o fallback "ATM do vencimento disponível" **não** entra na avaliação (origem descartada e contada). IV **com** o evento: é a previsão do mercado |

**Alvo:** RV realizada(*t*, *h*) = √((252/*h*)·Σᵢ₌₁..ₕ r²ₜ₊ᵢ), close-to-close de média zero, sem correção de viés. A janela que não tiver os *h* retornos é descartada e contada.

**Avaliação (RN-PRV-01, T-REF-09)**

- Horizontes avaliados: `forecast.evaluation_horizons_bd`, padrão **[21]** (= prazo constante, o que alimenta o edge na Etapa 5).
- **Origens não sobrepostas, ancoradas no fim:** a última origem *t*_K é o pregão tal que *t*_K + *h* = último pregão com fechamento; as anteriores são *t*_K − *h*, *t*_K − 2*h*, … (contadas em pregões do calendário). As janelas realizadas (*t*ₖ, *t*ₖ + *h*] são disjuntas: nenhum dia aparece em duas. Todas as previsões (modelos e baselines) usam as **mesmas origens**.
- Erro eₖ = σ̂ₖ − RVₖ, em pontos de vol (decimal). Métricas por modelo: **n** (e descartes, com motivo), **viés** (média de e), **MAE**, **RMSE** e, contra cada baseline, a **razão de RMSE** nas origens em que os dois existem (pareadas). < 1 = melhor que o baseline.
- Intervalos das métricas: **bootstrap percentil** (2.000 reamostragens das origens, semente fixa, nível `ci_level`).
- Abaixo da **amostra mínima de 8 janelas** (QA-08) a métrica é `insufficient_data` e o modelo **não pode ser escolhido** para o edge (RF-PRV-02, RN-PRV-02). Com 1 ano de histórico e *h* = 21, EWMA e combinação chegam a ~9–11 janelas; o GARCH só acumula janelas avaliáveis à medida que o histórico passa de 240 retornos antes da origem (LC-04).
- Recalculado no worker (job `forecast_recompute`) ao fim de cada `vol_recompute`; as telas só leem.

**Intervalo da previsão (QA-07, nível `vol.ci_level` = 90%)**

- **Empírico:** com ≥ 8 janelas avaliadas do mesmo modelo e horizonte, [σ̂·e^q_low, σ̂·e^q_high], com q = quantis (5% e 95% a 90%) de ln(RVₖ/σ̂ₖ). `origin = estimated`.
- **Fallback analítico:** abaixo disso, só o erro de amostragem da RV em *h* dias, supondo o modelo correto: *h*·RV²/σ̂² ~ χ²ₕ ⇒ [σ̂·√(χ²ₕ;₀,₀₅/*h*), σ̂·√(χ²ₕ;₀,₉₅/*h*)]. `origin = approximate`, motivo "intervalo só com o erro de amostragem (< 8 janelas avaliadas)": é estreito demais por ignorar o erro do modelo.
- Horizonte não avaliado (lido do estado): usa os quantis do horizonte avaliado mais próximo, `origin = approximate`, com o motivo.
- O mesmo método vale para a **RV close-to-close** da Etapa 3 (χ² com *n* da janela) e confirma o intervalo provisório do salto de evento (§5.5.1). Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang e intradiária seguem sem intervalo, com o motivo "sem distribuição fechada".

**Escolha do modelo (RF-PRV-04):** `forecast.selected_model` na configuração versionada (padrão **`ewma`**), escolhido pelo usuário em `/app/modelos` (cria uma versão nova de `config_versions`). O modelo escolhido só alimenta o edge num ativo e horizonte em que tiver avaliação disponível; sem ela, o edge fica "indisponível" com o motivo (Etapa 5). Não há troca automática pelo menor erro.

### 5.8 Simulador e dimensionamento (RF-SIM-01..05, RN-SIZ-01..06, Etapa 6) *(1.9)*

Decisões do usuário (2026-11-23): distribuição por **bootstrap reescalado** (QA-10); perda máxima = **maior entre ES 99% e stress** (QA-09); **estruturas compradas** incluídas (BRD 1.6); **banda de delta** como regra de hedge padrão da simulação (QA-11 parcial). Tudo configurável (blocos novos `simulation` e `sizing` de `config_versions`); valores sem calibração rotulados "não calibrado".

**Estruturas e pernas (RF-SIM-01)**

| `structure` | Pernas (por lote) | Direção | Hedge dinâmico |
|-------------|-------------------|---------|----------------|
| `short_straddle` | −call K, −put K | venda | banda de delta |
| `short_strangle` | −put K₁, −call K₂ (K₁ < K₂) | venda | banda de delta |
| `covered_call` | −call K, +ação (1 por opção) | venda | **nenhum**: a ação é a cobertura fixa da estrutura; um hedge dinâmico a transformaria em call vendida hedgeada |
| `long_straddle` | +call K, +put K | compra | banda de delta |
| `long_strangle` | +put K₁, +call K₂ | compra | banda de delta |

- Séries reais de `option_series` do ativo, não vencidas, todas no **mesmo vencimento**. Sugestões iniciais (editáveis): straddle no strike mais próximo de F; strangle e venda coberta nos strikes mais próximos de K/F = `edge.skew_moneyness` (0,95 e 1,05). Lote = `sizing.lot_size` (**100** opções; ação na mesma quantidade).
- Precificação: BS europeu com dividendos discretos e strike efetivo (§5.5.1); séries americanas seguem a limitação LC-01.

**Insumos e preços manuais (RF-SIM-03)**
- Padrão: último pregão — S = fechamento oficial; preço de cada perna = BS com a **IV de referência** da série (QA-04). Série sem IV de referência no último pregão → exige preço manual.
- Manual: S e/ou preço de cada perna, com data e hora; a IV da perna é recalculada (Newton protegido, §5.5.1; sem solução → erro explícito na perna, sem número). Tudo que usa valor manual sai com `origin = manual` e rótulo "manual".
- Horizonte *h* = dias úteis até o vencimento. σ̂(*h*) e intervalo do modelo escolhido, lidos do estado (§5.7; `approximate` quando *h* não for avaliado). *s* como na §5.6.1.

**Edge e semáforo da estrutura** — mesmas regras da §5.6.1 (comparações estritas, duas direções), com os insumos da estrutura:
- IV da estrutura = média das IVs das pernas de opção ponderada pela vega. Com evento confirmado ou estimado na vida da opção, IV ex-evento pelo método da §5.5.1; sem como separar, as métricas saem `approximate` com o motivo.
- Custos *c* em pontos: spread de cada perna pela faixa de moneyness dela (`option_spread_estimates`, conservador), taxas e corretagem como na §5.6.1, divididos pela vega da estrutura; hedge por Leland com `costs.hedge_interval_bd` (premissa conservadora do semáforo, igual à do ranking). A simulação mostra ao lado o custo de hedge **da regra de banda** (abaixo), para comparação.
- Prêmio *p* = IV − σ̂(1 + *s*) com intervalo [*p*_lo, *p*_hi]; estado e direção do sinal. Sem IV, σ̂ avaliado ou custos → **indisponível**.

**Distribuição simulada de P&L (RF-SIM-04, QA-10)**
- Amostra: retornos log diários close-to-close ajustados por proventos dos últimos `simulation.sample_bd` (**252**) pregões, **com os gaps** (os dias de evento ficam na amostra; nenhum salto extra é injetado). Menos de `simulation.min_returns` (**120**) → `insufficient_data`.
- Reescala (média zero, divisor *n*, coerente com a eq. 2.1b): zᵢ = (rᵢ − r̄)·σ̂_d/sₙ, com sₙ = √(Σ(rᵢ − r̄)²/*n*) e σ̂_d = σ̂/√252 (σ̂ central). A amostra reescalada tem média 0 e desvio exatamente σ̂_d; a forma (caudas, assimetria) é a do histórico.
- Caminhos: `simulation.paths` (**10.000**), sorteio i.i.d. com reposição, semente fixa `simulation.seed` (resultado determinístico para os mesmos insumos). Passo diário até o vencimento: Sₜ₊₁ = Sₜ·exp(zₜ − σ̂_d²/2 + r_d) − Dₜ₊₁ (r_d = taxa contínua diária; Dₜ₊₁ = provento com data ex no dia, quando houver).
- IV de cada perna **constante** na vida da simulação (risco de vega fica com o stress, abaixo); rótulo "IV constante".
- **Hedge (QA-11):** delta da carteira (opções + ação) calculado à **IV de entrada** (hedge na implícita: caminho suave, H5). Na entrada, hedge até delta zero. A cada fechamento, se |Δ| > meia-largura *b*·`lot_size`·lotes (*b* = `simulation.delta_band`, **0,10** por opção, "não calibrado"), ajusta **só até a borda** (H1, `rehedge` da referência). Custo de cada ajuste = |quantidade| × S × (meio spread conservador do ativo-objeto + `costs.underlying_fee_rate`). Covered call: sem ajustes.
- Caixa remunerado à Selic (taxa contínua diária) sobre prêmios e ação; proventos pagos à ação em carteira.
- Vencimento: opções liquidadas pelo valor intrínseco; a ação resultante do exercício e o hedge são zerados com meio spread + taxa. P&L do caminho = opções + hedge + caixa − todos os custos (entrada: meio spread + taxas + corretagem das pernas).
- Saída por lote, em R$: média, desvio-padrão, percentis (1, 5, 25, 50, 75, 95, 99), **ES 99%** (média das perdas no pior 1% dos caminhos), P(P&L < 0), nº médio de ajustes, custo médio de hedge e histograma (`simulation.histogram_bins`, **50**). Junto, a dispersão pela eq. 7.7 (Kamal-Derman), rotulada "aproximado" (H6).
- **P&L esperado líquido (RF-SIM-05)** = média da distribuição (σ̂ central, custos e regra de banda incluídos). Também o aproximado 𝒱 × (|*p*| − *c*) da §5.6.1.

**Payoff e Greeks (RF-SIM-02)** — sem hedge, em grade de S de ±`simulation.payoff_range` (**30%**) do S atual: no vencimento (intrínseco) e em `simulation.payoff_dates` (**hoje e metade da vida**) por BS à IV de entrada. Greeks por lote e por posição nas unidades da §5.1 (delta em ações, gamma por R$, theta por dia útil, vega por ponto). Custos estimados discriminados (opções: spread, taxas, corretagem; hedge: Leland e banda).

**Dimensionamento (RN-SIZ-01..06)**
- Capital *W* = `sizing.capital_brl` (informado pelo usuário; sem valor → o dimensionamento pede o capital e não sugere tamanho).
- **Kelly (RN-SIZ-02, eq. 8.14):** maximizar E[ln(*W* + *n*X)] para *n* lotes dá, para edge pequeno, *n** = *W*·μ/σ², com:
  - μ = P&L esperado por lote no **limite inferior do edge**: venda 𝒱_lote·(*p*_lo − *c*_venda); compra 𝒱_lote·(−*p*_hi − *c*_compra) (𝒱_lote em R$ por unidade de vol);
  - σ² = **variância da distribuição simulada** por lote (com as caudas do histórico; nunca a eq. 7.7 nem outra aproximação normal).
  - *n*_Kelly = ⌊`sizing.kelly_fraction` (**0,25**) × *W*·μ/σ²⌋ lotes.
  - **Zero** (RN-SIZ-05) se o estado não for "edge líquido", se a direção da estrutura for oposta à do sinal, se μ ≤ 0 ou se a simulação estiver indisponível; a tela diz qual.
- **Teto (RN-SIZ-03, QA-09):** perda máxima por lote *L* = max(ES 99%, pior perda de stress). Stress instantâneo na entrada sobre a estrutura com o hedge inicial, reprecificada por BS e zerada com meio spread + taxas: S × (1 ± `sizing.stress_gap`, **0,10**); IV + `sizing.stress_vol_pts` (**0,10**, todas as pernas); S × 0,90 com IV + 0,10. *n*_teto = ⌊`sizing.max_loss_fraction` (**0,07**) × *W* / *L*⌋.
- **Tamanho final** = min(*n*_Kelly, *n*_teto) com a regra que prevaleceu: `kelly`, `cap`, `tie` (iguais) ou `zero` (com o motivo) (RN-SIZ-04, PRD-UI-09).
- **Margem (RN-SIZ-06):** só manual, por lote, com data e hora; a tela mostra margem total × capital. A plataforma não estima margem nesta etapa.

**Registro da entrada (RF-DIA-01, RN-EDG-06, CS-01)** — `POST /positions` recebe só **insumos** (estrutura, séries, preços manuais com hora, capital, margem, lotes e preços executados por perna, custos reais, hedge inicial executado, nota) e `base_config_version_id` (409 se não for a vigente, como no `POST /config`). O engine **recalcula** edge, semáforo, simulação e dimensionamento e grava o retrato (§5.4).
- Semáforo **indisponível → recusado** (422 com o motivo): não existe entrada sem semáforo (CS-01 por construção).
- Estado ≠ "edge líquido" na direção da estrutura, ou lotes executados acima do sugerido → exige `override_reason` (texto); o retrato grava o override (A1 da referência).
- `positions`, `position_entries` (tipo `entry` nesta etapa) e `manual_inputs` **imutáveis** (trigger bloqueia UPDATE e DELETE, como em `config_versions`); o status da posição muda pelos lançamentos da Etapa 7.
- **Papéis do Postgres (backlog M-2 b):** dono das migrations × papel da aplicação sem DDL e sem UPDATE/DELETE nas tabelas imutáveis.

### 5.9 Diário, marcação D-1, atribuição, carteira e risco (RF-DIA-02..04, RF-RSK-01..04, RS-06, Etapa 7) *(1.10)*

Decisões do usuário (2026-11-24): **QA-12** medida no COTAHIST anual de 2017 e 2020 com choque de vol pela IV ATM aproximada (fallback na RV); marcação pela **IV de referência**; correção por **estorno**; limites com a **proposta padrão** (não calibrada). Blocos novos `journal` e `risk` em `config_versions`; valores sem calibração rotulados "não calibrado".

**Lançamentos (RF-DIA-02/03, RS-06)** — `POST /positions/{id}/entries`, só insumos, append-only; tabela `position_entries` continua imutável.

| `kind` | Instrumento | Efeito nas quantidades | Preço gravado |
|--------|-------------|------------------------|---------------|
| `hedge` | ação do ativo-objeto | ± quantidade de ações | preço executado |
| `exit` | uma perna de opção ou a ação | reduz a quantidade em direção a zero (parcial ou total); vencimento sem exercício = `exit` a preço 0 | preço executado |
| `exercise` | perna **comprada** | opção → 0 na quantidade exercida; ação ± a mesma quantidade (call: +, put: −) ao strike efetivo | strike efetivo |
| `assignment` | perna **vendida** | opção → 0 na quantidade designada; ação ∓ (call: −, put: +) ao strike efetivo | strike efetivo |
| `strike_adjustment` | perna de opção | strike efetivo e quantidade novos da perna (ex.: provento, bonificação), conforme o aviso da B3 | novo strike efetivo (`strike_after`); `quantity` = quantidade da perna **depois** do ajuste (a diferença entra a preço 0). A marcação continua usando o strike oficial do pregão; `strike_after` fica como registro |
| `roll` | perna de opção | como `exit`, gravado junto com a nova posição (abaixo) | preço executado |
| `void` (estorno) | o do lançamento anulado | desfaz o efeito do lançamento ligado (`linked_entry_id`) | — ; `void_reason` obrigatório |

- Cada lançamento grava data e hora de execução, taxas e corretagem reais, nota opcional, `config_version_id` e `engine_version`.
- **Validações (RS-06), 422 com o motivo:** instrumento pertence à posição (pernas do retrato ou ação do ativo-objeto); posição aberta (exceto `void`); data de execução ≥ a da entrada e ≤ agora; quantidade de uma perna nunca troca de sinal nem passa de zero no `exit`/`exercise`/`assignment`; `exercise` só em perna comprada e `assignment` só em vendida; série europeia só no dia do vencimento, americana até ele; `void` só de lançamento não anulado, nunca de `entry` (a entrada se desfaz encerrando a posição) nem de outro `void`, e recusado se deixar alguma quantidade inconsistente nos lançamentos posteriores.
- **Status** (derivado, a posição continua imutável): **aberta** enquanto houver quantidade ≠ 0 em qualquer perna ou na ação; **encerrada** quando tudo zera. Passado o vencimento com opção ainda em aberto → aviso "lançar exercício, designação ou vencimento sem exercício" (LC-08).
- **Rolagem (RN-GES-04, CS-01):** `POST /positions` com `roll_from` = {posição de origem, preços e custos de fechamento por perna}. Na mesma transação, grava os `roll` na origem e a nova posição com retrato próprio (semáforo obrigatório, mesmo fluxo e mesmas regras de `override_reason` da §5.8); `positions.rolled_from_position_id` liga as duas. A sugestão de rolagem fica na Etapa 8.

**Marcação D-1 (`daily_marks`)** — job `marks_recompute` no worker, enfileirado ao fim de cada `forecast_recompute` e a cada lançamento (só a posição afetada, a partir da data do lançamento). Idempotente; dado derivado (pode ser refeito), grava `config_version_id` e `engine_version`.
- Para cada posição e cada pregão *t* da entrada até o último pregão coletado (e até o encerramento): quantidades no fechamento de *t* (lançamentos executados até o fim de *t*), S = fechamento oficial (`daily_bars`).
- Opção: preço = BS com a **IV de referência** da série em *t* (`option_daily_quotes`, QA-04), `origin = observed`. Sem IV: **fechamento oficial do COTAHIST**, IV recalculada desse preço, `origin = approximate`. Sem nenhum dos dois (ou sem solução da IV): repete a IV da marcação anterior e reprecifica com o S do dia, `stale = true`, rótulo "desatualizado". No primeiro pregão sem nenhum dos dois, o preço executado na entrada (`approximate`). Opção no dia do vencimento: valor intrínseco; depois dele, o intrínseco do pregão do vencimento, sem Greeks.
- Greeks por perna e da posição (ação incluída no delta), nas unidades da §5.1, à IV da perna, com o tempo até o vencimento em anos úteis, a taxa e os proventos do dia (BS com dividendos discretos, strike efetivo).
- Grava por posição e pregão: S, valor de mercado das opções e da ação, Greeks da posição e, em JSONB, cada perna (quantidade, preço, IV, origem, Greeks e os insumos da reprecificação usados pelo stress: tipo, strike efetivo, prazo, taxa contínua e VP dos proventos).

**Atribuição diária (`pnl_attribution`, RF-DIA-04, CS-04)** — entre os pregões *t*−1 e *t* consecutivos com marcação, com as quantidades do fechamento de *t*−1 e os Greeks da marcação de *t*−1 (expansão de Taylor, eq. 1.4 da referência):
- ΔS* = Sₜ + Dₜ − Sₜ₋₁ (Dₜ = provento com data ex em *t*): retorno ajustado como em RN-VOL-07; o provento recebido ou pago pela ação em carteira entra no P&L de mercado.
- **delta** = Δₜ₋₁·ΔS*; **gamma** = ½·Γₜ₋₁·(ΔS*)²; **theta** = Θₜ₋₁·*n*_du (Θ por dia útil; *n*_du = dias úteis entre os pregões); **vega** = Σ_pernas 𝒱ₜ₋₁·(IVₜ − IVₜ₋₁)/0,01 (vega por ponto, IV de cada perna).
- **P&L de mercado** = (valor das opções + ação)ₜ − (mesmo conjunto)ₜ₋₁ + q_ação·Dₜ, sempre com as quantidades de *t*−1; **resíduo** = P&L de mercado − (delta + gamma + theta + vega). Sempre exibido.
- **Execução e custos** (linha própria, fora do resíduo): para cada lançamento executado em *t*, q·(marcaçãoₜ − preço executado) − taxas − corretagem. No dia da entrada só existe esta linha (diferença entre o pago e a marcação, incluindo meio spread). Exercício e designação: a opção sai a preço 0 e a ação entra ao strike, de modo que, no vencimento, a linha soma só os custos.
- Invariante: Σ (mercado + execução e custos) ao longo da vida = P&L realizado pelos fluxos de caixa da posição, com o valor de mercado das quantidades abertas na última marcação (teste exato em `Decimal`).
- Dia com marcação `stale` em alguma perna: a atribuição do dia sai com o rótulo "desatualizado" e conta para o CS-04 do mesmo jeito.
- **CS-04 por operação:** razão = Σₜ|resíduoₜ| ÷ Σₜ(|deltaₜ| + |gammaₜ| + |thetaₜ| + |vegaₜ|); meta < `journal.residual_max_ratio` (**0,15**, do BRD). **Sinal de erro de lançamento (RS-06):** dia com |resíduo| > 0,15 × (soma dos módulos do dia) **e** |resíduo| ≥ `journal.residual_min_brl` (**R$ 50**, não calibrado; evita disparo em dias parados) aparece marcado na operação.
- **Banda de delta (fluxo 3):** a operação mostra o delta da última marcação contra a banda da simulação (`simulation.delta_band` × lote × lotes) com o estado "dentro" / "fora da banda". É um indicador calculado na leitura; o alerta persistente (`alerts`), a banda por tempo e a configuração própria do hedge ficam na Etapa 8 (RN-GES-01).

**Carteira (RF-RSK-01/02)** — `GET /portfolio`, calculado na leitura a partir da última marcação de cada posição aberta (`as_of` de cada uma; marcações de datas diferentes → aviso):
- Greeks da carteira e por ativo: delta em ações e em R$ (Δ·S), gamma (Δ por R$ e P&L de um movimento de 1%: ½·Γ·(0,01·S)²), theta por dia útil, vega por ponto.
- Exposição por vencimento: por (ativo, vencimento), lotes, valor de mercado, delta, gamma, theta e vega.

**Stress (RF-RSK-03, QA-12)** — reprecificação completa por BS de cada perna e da ação, **instantânea** (sem passar o tempo), com o hedge atual e sem custos de saída (a perda de saída já está no teto da Etapa 6):
- Cenários padrão (`risk.stress_*`): S × 1,10; S × 0,90; IV + 0,10 (todas as pernas); S × 0,90 com IV + 0,10; e os **cenários de crise** de cada ativo (mai/2017 e mar/2020), cada posição com os choques do seu próprio ativo.
- `POST /portfolio/stress` aceita um cenário avulso (gap, choque de vol em pontos) e não grava nada.
- Saída: perda por cenário na carteira, por ativo e por vencimento; IV nunca abaixo de 0,01 após o choque.

**Cenário de crise histórica (QA-12)** — job `crisis_measure`, disparado sob demanda na tela de configurações (e ao incluir ativo novo), grava em `crisis_measurements`:
- Fonte: COTAHIST **anuais de 2017 e 2020**, baixados uma vez pelo adaptador existente (cache bruto, ZIP seguro, pré-filtro do ativo e das suas opções); nada entra em `daily_bars` (o histórico diário do sistema continua com 1 ano). Selic e proventos dos episódios pelos adaptadores do BCB e do Yahoo (proventos `estimated`).
- Episódios (`risk.crisis_episodes`, editáveis): **mai/2017** = 10/05/2017 a 31/05/2017; **mar/2020** = 17/02/2020 a 31/03/2020.
- **Choque de preço:** pior retorno log acumulado em `risk.crisis_horizon_bd` (**5**) pregões consecutivos dentro do episódio, ajustado por proventos, no fechamento oficial; gravado como retorno simples (S × e^r − S). Também o pior dia, só para exibição.
- **Choque de vol:** IV ATM no último pregão da janela − IV ATM no pregão anterior ao início, em pontos. IV ATM de um pregão = média das IVs da call e da put com strike mais próximo do fechamento do ativo, no primeiro vencimento com ≥ 10 du, a partir do **preço de fechamento** de cada opção (Newton protegido, §5.5.1) e do fechamento do ativo, `origin = approximate` (fechamentos não sincronizados). Exige as duas pernas com ≥ `costs.min_trades` (**20**) negócios no dia; sem isso, **fallback** = RV close-to-close 20 pregões no fim − no início, também `approximate`, com o motivo.
- Ativo sem negociação no episódio → `unavailable` com o motivo. Valores manuais em `risk.crisis_overrides` (por ativo e episódio) substituem os medidos, com `origin = manual`.
- **Teto do dimensionamento (Etapa 6, QA-09):** *L* = max(ES 99%, pior perda dos stresses simples, pior perda dos cenários de crise do ativo). Crise indisponível → *L* sem ela, com o motivo no retrato.

**Limites (RF-RSK-04, PR-04)** — `GET /portfolio/limits`, calculados na leitura; capital = `sizing.capital_brl` (sem capital → `unavailable`, "informe o capital"). Padrões não calibrados (`risk.limits`):

| Limite | Fórmula | Padrão |
|--------|---------|--------|
| Perda em stress | pior perda da carteira entre os cenários ÷ capital | ≤ **0,20** |
| Vega total | \|vega da carteira por ponto\| ÷ capital | ≤ **0,01** |
| Concentração por ativo | pior perda em stress das posições do ativo ÷ (limite de perda em stress × capital) | ≤ **0,50** |
| Concentração por vencimento | idem, por vencimento | ≤ **0,60** |

- Estado por limite: `ok`, `breached` (comparação estrita: igual ao limite é `ok`) ou `unavailable`, com o valor e o uso do limite. A concentração usa o orçamento de perda, e não a participação na carteira, para fazer sentido com uma única posição.
- **Pró-forma na entrada (PR-04):** `POST /sizing` e `POST /positions` devolvem os limites da carteira **com a nova posição** (marcação de entrada). Limite ultrapassado → `override_reason` obrigatório no registro, como na §5.8; o retrato grava o estado dos limites.
- Alertas persistentes de limite ficam na Etapa 8 (RN-GES-05); nesta etapa o estado aparece em `/app/carteira`, no simulador e no painel.

**Configuração nova (§5.3):** `journal` {`residual_max_ratio` 0,15, `residual_min_brl` 50}; `risk` {`stress_gap` 0,10, `stress_vol_pts` 0,10, `crisis_episodes`, `crisis_horizon_bd` 5, `crisis_overrides` {}, `limits` {0,20; 0,01; 0,50; 0,60}}. Versão nova criada automaticamente com os padrões, como nas etapas anteriores. Os stresses do `sizing` (Etapa 6) passam a ler `risk.stress_*`, para a carteira e o teto usarem os mesmos choques.

### 5.10 Gestão da operação: alertas de hedge, saída, rolagem, limites e proventos (RN-GES-01..07, RS-07, Etapa 8) *(1.11)*

Decisões do usuário (2026-11-24, QA-11): banda de hedge = **banda da simulação**, alerta por tempo **desligado**; "o edge acabou" pela **estimativa pontual ≤ 0**; **stop e meta desligados** (regra G2 da referência); prazo de **5 du**; rolagem para o **primeiro vencimento com ≥ 10 du**. Bloco novo `management` em `config_versions`. Todos os valores rotulados "não calibrado".

**Avaliação** — job `alerts_evaluate` no worker, enfileirado ao fim de cada `marks_recompute` (portanto depois de cada coleta e de cada lançamento), depois de `POST /config` e de cada criação, edição ou exclusão de evento com provento. Um pedido na fila absorve os seguintes. O job avalia todas as posições abertas na **última marcação** de cada uma (pregão *t*) e a carteira. É idempotente e não recalcula marcações: lê `daily_marks`, `pnl_attribution`, o estado da previsão e os spreads já gravados. Nenhum endpoint de leitura avalia regras.

**Regras** (comparações como abaixo; "não calibrado" em todos os parâmetros):

| `kind` | `rule` | Dispara quando | Parâmetro (padrão) |
|--------|--------|----------------|--------------------|
| `hedge` | `hedge_band` | \|Δ da posição\| > *b* × `sizing.lot_size` × lotes (estrita; igual à borda não dispara), com o Δ da última marcação (ação incluída). Detalhe: Δ, borda e a quantidade de ações que leva o delta **até a borda** (H1) | *b* = `simulation.delta_band` (**0,10**), o mesmo parâmetro da simulação |
| `hedge` | `hedge_time` | pregões desde o último `hedge` não estornado (ou desde a entrada) ≥ *N* e Δ ≠ 0 | `management.hedge_interval_bd` (**desligado**, `null`) |
| `exit` | `exit_edge` | edge relativo líquido da posição (abaixo) ≤ 0, pela estimativa pontual; o intervalo vai no detalhe | sempre ligado |
| `exit` | `exit_dte` | du de *t* até o vencimento mais próximo entre as pernas de opção abertas ≤ *N* | `management.exit_dte_bd` (**5**) |
| `exit` | `exit_profit` | P&L acumulado (mercado + execução e custos, §5.9) ≥ *f* × P&L esperado na entrada (média simulada por lote do retrato × lotes executados); P&L esperado ≤ 0 → regra indisponível na posição | `management.profit_target_fraction` (**desligado**; ao ligar, sugestão 1,0) |
| `exit` | `exit_stop` | P&L acumulado ≤ −*f* × *L* × lotes (*L* = perda máxima por lote do retrato, §5.8) | `management.stop_loss_fraction` (**desligado**; ao ligar, sugestão 1,0) |
| `roll` | `roll_suggested` | algum alerta de saída (`exit_edge` ou `exit_dte`) ativo na posição **e** o destino (abaixo) tem edge líquido na direção da posição, com os custos de fechar a atual | `management.roll_min_dte_bd` (**10**) |
| `limit` | `limit_stress`, `limit_vega`, `limit_underlying`, `limit_expiry` | estado `breached` em `GET /portfolio/limits` (§5.9, comparação estrita); um alerta por limite e, nas concentrações, por ativo ou vencimento | `risk.limits` (Etapa 7) |
| `dividend` | `dividend_upcoming` | provento (`corporate_actions`, qualquer fonte; rótulo da origem e "estimado" quando for o caso) do ativo de uma posição aberta com data ex em (último pregão coletado, + *N* du] | `management.dividend_lead_bd` (**5**) |
| `dividend` | `strike_adjustment_pending` | ajuste de strike detectado (`series_adjustments`, RN-DAD-03) numa série de perna aberta, com `effective_date` depois da entrada, sem lançamento `strike_adjustment` não estornado nessa perna com execução ≥ `previous_date` | — |

**Edge da posição aberta (RN-GES-02, G1)** — a pergunta é "eu manteria esta posição agora?". Mesmos métodos do edge da estrutura (§5.8), com as pernas de opção **abertas** na marcação de *t*:
- *h* = du de *t* até o vencimento; IV = média das IVs da marcação ponderada pela \|vega\| de cada perna (ex-evento como na §5.8); σ̂(*h*) e intervalo do modelo escolhido; *s* da §5.6.1. *p* = IV − σ̂(1 + *s*), com [*p*_lo, *p*_hi].
- Custos em pontos (÷ \|vega da posição\| por unidade de vol): **manter** = hedge por Leland até o vencimento, na direção da posição, com `costs.hedge_interval_bd` (zero na venda coberta, que não tem hedge dinâmico); **fechar** = meio spread conservador da faixa de cada perna × preço da marcação + taxas e corretagem das pernas, mais a ação em carteira (\|q\|·S·(meio spread do ativo-objeto + `costs.underlying_fee_rate`)).
- Edge relativo líquido da posição: venda (*p* − *c*)/σ̂; compra (−*p* − *c*)/σ̂.
- Sem IV, σ̂ avaliado ou custos, ou com *h* < 1 → regra **indisponível** na posição, com o motivo (PRD-UI-08). Nunca dispara sem número; a tela da operação mostra o estado.

**Rolagem (RN-GES-04)** — avaliada no mesmo job, só para posições com `exit_edge` ou `exit_dte` ativo:
- Destino: **mesma estrutura** e direção, ativo igual, **primeiro vencimento** com du a partir de *t* ≥ `management.roll_min_dte_bd`, strikes pela sugestão do simulador (§5.8). Sem séries com IV de referência em *t* → "sem destino" com o motivo.
- Edge e semáforo do destino pela §5.8, somando aos custos *c* do destino os **custos de fechar a posição atual** (acima), convertidos em pontos pela vega do destino. Só vira `roll_suggested` se o estado for **edge líquido na direção da posição** (comparação estrita). Caso contrário, o alerta de saída mostra "rolagem avaliada: sem edge líquido" com os números.
- A sugestão abre `/app/simulador?roll_from={id}` com o destino preenchido. O registro segue a §5.9 (`POST /positions` com `roll_from`, semáforo obrigatório, `override_reason` quando exigido). O alerta não registra nada sozinho.

**Ciclo de vida (RN-GES-07)**
- Chave do alerta: (`rule`, posição ou nenhuma, `scope_key`), em que `scope_key` é o limite e o ativo ou vencimento, a data ex do provento ou a série ajustada. No máximo **um alerta não resolvido por chave** (índice único parcial).
- Condição nova → `active`, com `config_version_id` e `engine_version` **do disparo**, o pregão *t* e o detalhe (valores, limiar, intervalo, rótulos). Condição que continua → atualiza `last_as_of`, o detalhe e `evaluated_config_version_id`; o estado (`active`/`seen`) não muda. Condição que some, ou posição encerrada → `resolved`, `resolved_by = auto`, com o motivo. Se voltar a valer, abre um alerta novo.
- Usuário: `active` → `seen`; `active`/`seen` → `resolved` (`resolved_by = user`, nota opcional). `resolved` é terminal. Se o usuário resolver um alerta cuja condição continua, o próximo job não o reabre até a condição sumir e voltar (evita alerta repetido); a tela da operação continua mostrando o estado atual da regra.
- Alertas não são apagados. O papel da aplicação tem INSERT e UPDATE, sem DELETE; um trigger impede mudar `kind`, `rule`, posição, `scope_key`, `config_version_id`, a data do disparo e qualquer coluna de um alerta resolvido.

**Configuração nova (§5.3):** `management` {`hedge_interval_bd` `null`, `exit_dte_bd` 5, `profit_target_fraction` `null`, `stop_loss_fraction` `null`, `roll_min_dte_bd` 10, `dividend_lead_bd` 5}. Versão nova criada automaticamente com os padrões, como nas etapas anteriores. A banda de hedge continua em `simulation.delta_band`.

*(Ajustes na implementação, 2026-11-24, sem mudança de escopo)*
- **Reabertura depois da resolução pelo usuário:** a coluna `alerts.persisting` marca o alerta resolvido pelo usuário com a condição ainda valendo; o job a passa para falso quando a condição some (única mudança permitida num alerta resolvido, verdadeiro → falso). Assim a regra "não reabre até a condição sumir e voltar" não precisa de tabela à parte.
- **Estado das regras por posição:** `position_management` (derivada, uma linha por posição aberta, refeita pelo job e apagada quando a posição encerra) guarda regras, edge e rolagem da última avaliação, para `GET /positions/{id}` mostrar o estado sem avaliar regras na leitura.
- **Destino da rolagem:** o primeiro vencimento com ≥ `roll_min_dte_bd` du **posterior ao vencimento atual** da posição (rolar para o mesmo vencimento não é rolagem). Só as pernas de opção são roladas (regra da §5.9); o hedge em ações continua na origem e é fechado com `exit`.
- **Gatilhos do job:** além de `marks_recompute` e `POST /config`, também `PUT /models/selection` (troca o modelo do edge, que muda o edge da posição).
- **Rolagem sem preço sugerido:** sem marcação D-1 na origem, o preço de fechamento de cada perna fica em branco no simulador e é obrigatório.

---

## 6. Modelo de dados (lógico)

Os nomes físicos foram confirmados nas Etapas 1 (`users`, `config_versions`, `jobs`) e 2 (tabelas de dados: migration `0003`). Todas as tabelas de usuário têm `user_id`; os dados de mercado (`option_series`, `trades`, `daily_bars` etc.) são compartilhados e não têm.

Detalhes confirmados na Etapa 2:
- `trades`: chave (pregão de referência, instrumento, `DataNegocio`, ID, ação de atualização). **A B3 reinicia os IDs a cada pregão** e o negócio de D-1 reapresentado pode repetir o ID de um negócio do dia (PETR4, 18/11/2026, ID 353710); a linha de cancelamento repete o ID do negócio cancelado. A R4 é calculada na gravação (`r4_valid`).
- `raw_files`: uma linha por consulta (`source`, `query_key`, `query_date`); o arquivo em disco é endereçado pelo SHA-256 (`{fonte}/{sha[:2]}/{sha}.{ext}`), então conteúdo idêntico é gravado uma vez.
- `collection_items`: `key` = ticker, ano (COTAHIST anual) ou `-`; `phase` define a ordem (COTAHIST anual → diário → Selic e proventos → ativo-objeto → opções). HTTP 404 é falha definitiva só para negócios (ticker inexistente); nas demais fontes pode ser arquivo ainda não publicado e é tentado de novo.
- `corporate_actions`: o ajuste de strike do COTAHIST gera um provento oficial implícito (`source = b3_strike_adjustment`, a redução mais frequente do dia, com ao menos 3 séries) para conferir o Yahoo (RS-02).
- Parâmetros da coleta (filtro de liquidez e janelas) ficam em `config_versions.params.collection`; a primeira coleta cria a versão inicial com os padrões do QA-06.

### 6.1 Referência

| Tabela | Conteúdo | BRD |
|--------|----------|-----|
| `users` | usuário fixo na fase 1 | ADR-13 |
| `underlyings` | ativos cadastrados pelo usuário (máx. 10), ativo/inativo | §5.1 |
| `option_series` | código, **ISIN do ativo-objeto**, vencimento, strike vigente, call/put, estilo + `style_source` (`name_suffix` \| `official_registry`), fonte, vigência (primeiro e último pregão). **Chave natural: (código, vencimento)**, pois códigos são reutilizados | RN-DAD-02 |
| `series_adjustments` | ajustes de strike e mudanças de código por provento, com data, strike anterior e novo (detectados no COTAHIST) e vínculo série antiga → nova | RN-DAD-03 |
| `exchange_holidays` | feriados B3, com `source` (`b3_official` \| `national_list` \| `b3_rule`) e `confirmed`. Carga inicial: lista nacional 2001–2078 (`feriados.csv`, formato ANBIMA: `DD/MM/AAAA;;`) + regras B3 (20/11 desde 2024, 24/12, 31/12); anos não publicados pela B3 ficam provisórios | RN-PRC-05, QA-02 |
| `risk_free_rates` | Selic diária (SGS) | RN-PRC-03 |
| `corporate_actions` | dividendos e JCP: data ex, valor, tipo, fonte (`manual` \| `yahoo` \| `b3_strike_adjustment`), confirmado/estimado | RN-PRC-02, RS-02 |

### 6.2 Mercado

| Tabela | Conteúdo | BRD |
|--------|----------|-----|
| `raw_files` | fonte (`b3_trades` \| `b3_cotahist`), caminho, hash sha256, ticker consultado, data consultada, momento da consulta, status HTTP, tamanho, formato, status de parsing | RF-DAD-03/04 |
| `trades` | negócios brutos normalizados (instrumento, data, hora, preço, quantidade, ação de atualização, sessão, id do negócio). **Particionada por mês.** Chave única (instrumento, data, id do negócio). | RF-DAD-01 |
| `daily_bars` | OHLC, nº de negócios, quantidade e volume oficiais do ativo-objeto por pregão (COTAHIST), mais o resultado da verificação contra a reconstrução R4 quando houver negócios intradiários | RN-DAD-01 |
| `option_daily_stats` | linha do COTAHIST por série e pregão (OHLC, médio, último, melhor oferta de compra/venda no fechamento, nº de negócios, quantidade, volume); base do pré-filtro da coleta | RF-DAD-02, QA-06 |
| `option_daily_quotes` | **IV de referência** diária por série (mediana das IVs sincronizadas na última hora, RN-VOL-06), preço implícito, nº de negócios usados, status (`ok` \| `low_sample`), flag de liquidez | QA-04, QA-06 |
| `implied_vols` | IV por negócio, com preço sincronizado do ativo e defasagem em ms; pares acima da janela (padrão 10 s) não geram IV e são contados | RF-VOL-02, RN-VOL-03 |
| `atm_term_structure` | IV ATM por vencimento e IV de prazo constante (ou indisponível, com motivo) | RF-VOL-03, RN-VOL-05 |
| `intraday_bars` | barras de 5 min do ativo-objeto por pregão (início, último preço, nº de negócios, quantidade), a partir dos negócios válidos pela R4, e a cobertura do pregão (% de barras com negócio, completo/incompleto) | RN-VOL-08 |
| `intraday_sessions` | *(1.6)* resumo do pregão intradiário: grade (abertura, fim da sessão, tamanho da barra), barras totais e com negócio, cobertura, completo, Σ r² intradiário (sem a noite) | RN-VOL-08 |
| `constant_maturity_vols` | *(1.6)* IV de prazo constante por ativo e pregão (sem remoção de eventos), vencimentos usados ou o vencimento de fallback com o prazo efetivo | RF-VOL-03, RN-VOL-05 |
| `option_spread_estimates` | *(1.8)* spread estimado por ativo, pregão e faixa (`low`, `atm`, `high`, `underlying`): nº de séries e de negócios, mediana e p75 do spread relativo, mediana do spread de fechamento do COTAHIST, `config_version_id`; gravado no `vol_recompute` (§5.6.1) | RN-CST-03 |
| `realized_vols` | RV por ativo, pregão de referência, **estimador** (`close_to_close`, `close_to_close_demeaned`, `parkinson`, `garman_klass`, `rogers_satchell`, `yang_zhang`, `intraday_5m`) e janela (`window_bd`): valor, nº de pregões usados, status (`ok` \| `insufficient_data`) e motivo | RF-VOL-01 |

### 6.3 Coleta

| Tabela | Conteúdo | BRD |
|--------|----------|-----|
| `collection_runs` | execução: origem (manual / carga inicial), início, fim, status, totais | RF-DAD-06 |
| `collection_items` | um item por fonte × ticker × pregão (o COTAHIST do pregão é um item próprio e vem primeiro): status (pendente, ok, vazio, falha), tentativas, erro, `raw_file_id`. ZIP só com cabeçalho → `vazio`; HTTP 404 → `falha` sem nova tentativa | RF-DAD-02, RF-DAD-06 |
| `jobs` | fila genérica do worker (tipo, payload, status, lock) | ADR-08 |

### 6.4 Eventos, previsão e modelos

| Tabela | Conteúdo | BRD |
|--------|----------|-----|
| `events` | tipo (resultado, ex-dividendo, ex-JCP, Copom, macro), data, confirmada/estimada, valor por ação (ex-dividendo/ex-JCP). *(1.6)* Vencimentos não são gravados: derivados das séries mensais na leitura. Ex-dividendo/ex-JCP criam um provento `manual` em `corporate_actions` (`event_id`, apagado junto) e enfileiram o recálculo do ativo | RF-EVT-01/02, RS-02 |
| `event_jumps` | salto estimado por evento: pela estrutura a termo e pelo histórico, com intervalo. *(1.6: não persistida na Etapa 3 — calculado na leitura a partir de `atm_term_structure`, `daily_bars` e `realized_vols`, pois depende do calendário do usuário e é barato; volta a ser gravado no retrato da decisão, Etapa 6)* | RN-EVT-01/02 |
| `rv_forecasts` | previsão por modelo, ativo, data e horizonte, com intervalo. *(1.7)* Chave (ativo, pregão, modelo, `horizon_bd`); guarda também o **estado** do modelo (JSONB: λ e v; ω, α, β e σ²; componentes da combinação; nº de retornos), status, motivo, `config_version_id` e `engine_version` | RF-PRV-01/02 |
| `forecast_evaluations` | erro por modelo e baseline, apenas janelas não sobrepostas, nº de observações. *(1.7)* Chave (ativo, modelo, `horizon_bd`): n, descartes, viés, MAE, RMSE com intervalo, razão de RMSE contra cada baseline com intervalo, quantis do erro log (para o intervalo da previsão), status, `config_version_id`, `engine_version` | RF-PRV-03, RN-PRV-01 |
| `forecast_evaluation_points` | *(1.7)* uma linha por origem avaliada: origem, fim da janela, previsão, RV realizada (gráfico previsto × realizado e auditoria do T-REF-09) | RF-PRV-03, CS-03 |

### 6.5 Configuração, operações e risco

| Tabela | Conteúdo | BRD |
|--------|----------|-----|
| `config_versions` | snapshot JSONB imutável de todos os parâmetros | §7.11 |
| `positions` | operação: estrutura, ativo, status (aberta / encerrada), retrato da decisão, `config_version_id`. *(1.9)* Também direção, `engine_version`, `override_reason`; imutável (trigger), o status vem dos lançamentos | RF-DIA-01 |
| `position_entries` | lançamentos tipados: entrada, hedge, ajuste de strike, exercício, designação, saída, rolagem (fechamento + abertura ligados), com preço, quantidade e custos reais | RF-DIA-02/03, RN-GES-04 |
| `daily_marks` | marcação D-1 por posição: preços, IV, Greeks | §6 do BRD |
| `pnl_attribution` | P&L diário por delta, gamma, theta, vega e resíduo | RF-DIA-04 |
| `alerts` | tipo (hedge, saída, rolagem, limite, provento), regra, posição, estado (ativo / visto / resolvido), `config_version_id` | §7.9 |
| `manual_inputs` | preços do momento e margem informados pelo usuário, com hora | RF-SIM-03, RN-SIZ-06 |

*(1.10)* Na Etapa 7: `position_entries` ganha o tipo `void` (estorno, no máximo um por lançamento) e as colunas `strike_after`, `void_reason`, `note`, `config_version_id` e `engine_version`; `positions` ganha `rolled_from_position_id` (as duas continuam imutáveis; colunas novas só por migration); `daily_marks` (chave posição × pregão) e `pnl_attribution` (chave posição × pregão; delta, gamma, theta, vega, resíduo, mercado, execução e custos, `stale`, sinal de erro) são derivadas e refeitas pelo `marks_recompute`; `crisis_measurements` (usuário, ativo, episódio, janela, choque de preço, choque de vol, método, origem, motivo, data da medição; por usuário porque o episódio vem da configuração de cada um). Lançamentos e rolagem travam a operação (lock consultivo de transação) antes de validar. Os limites usam sempre o capital da configuração (`sizing.capital_brl`), nunca o do pedido. A tabela `alerts` fica para a Etapa 8.

*(1.11)* Na Etapa 8 entra `alerts`: `kind`, `rule`, `position_id` (nulo nos limites de carteira), `scope_key`, `state` (`active`/`seen`/`resolved`), `triggered_at`, `triggered_as_of`, `last_as_of`, `details` (JSONB), `config_version_id` (do disparo), `evaluated_config_version_id`, `engine_version`, `resolved_at`, `resolved_by` (`auto`/`user`), `resolution_note`. Índice único parcial em (`rule`, posição, `scope_key`) onde `state <> 'resolved'`. O papel da aplicação tem INSERT e UPDATE, sem DELETE; um trigger protege as colunas do disparo e torna o alerta resolvido imutável (§5.10).

*(1.9)* Na Etapa 6 entram `positions`, `position_entries` (só o tipo `entry`) e `manual_inputs`, todas imutáveis por trigger, e o papel da aplicação no Postgres passa a ser separado do dono das migrations (sem DDL e sem UPDATE/DELETE nas tabelas imutáveis: `config_versions`, `positions`, `position_entries`, `manual_inputs`).

---

## 7. Contrato da API (engine)

Base: `/api/engine` no navegador (via `rewrites`) e `http://127.0.0.1:8000` para Server Components. Todas as respostas com estimativas usam `EstimatedValue` (§5.2). Erros seguem o formato *problem details* (RFC 9457).

| Grupo | Endpoints principais | BRD |
|-------|----------------------|-----|
| Saúde | `GET /health` (versão do engine, banco, última coleta) | — |
| Coleta | `GET /collection/pending` (pregões e itens pendentes) · `POST /collection/runs` · `GET /collection/runs/{id}` (progresso) · `GET /collection/gaps` (relatório de falhas e lacunas) | RF-DAD-02/05/06 |
| Ativos e séries | `GET/POST/PATCH /underlyings` · `GET /underlyings/{t}/series` · *(1.6)* `GET /underlyings/{t}/summary` (último pregão, qualidade do intradiário e da sincronização) · `GET /underlyings/{t}/prices` | §5.1, RN-DAD-02, RN-VOL-03 |
| Volatilidade | `GET /underlyings/{t}/vol/realized` · `/vol/implied/smile?expiry=` · `/vol/term-structure` · `/vol/constant-maturity` | RF-VOL-01..05 |
| Eventos | `GET/POST/PATCH/DELETE /events` · `GET /underlyings/{t}/event-jumps` | §7.3 |
| Previsão | `GET /forecasts?underlying=&horizon_bd=&model=` · `GET /models/evaluation` · *(1.7)* `GET /models/evaluation/points?underlying=&model=&horizon_bd=` · `PUT /models/selection` (grava `forecast.selected_model` numa versão nova de configuração; a única escrita desta etapa) | §7.1 Previsão |
| Ranking | `GET /ranking` *(1.8: uma linha por ativo ativo, com estado, direção, IV, σ̂, *s*, prêmio, edge relativo e líquido com intervalos, custos discriminados, IV rank, skew, estrutura a termo, eventos, liquidez, `config_version_id` e modelo)* · `GET /underlyings/{t}/spreads` (estimativas por faixa e pregão) | §7.4, RN-CST-03 |
| Simulação | `POST /simulations` (estrutura, séries, preços manuais opcionais) → payoff, Greeks, custos, distribuição de P&L, P&L esperado. *(1.9)* Também o edge e o semáforo da estrutura; `GET /underlyings/{t}/chain?expiry=` (séries não vencidas com strike efetivo, IV de referência e preço do último pregão, para montar as pernas) | §7.6 |
| Dimensionamento | `POST /sizing` (simulação, capital, margem manual) → Kelly, teto, tamanho final e regra que prevaleceu. *(1.9)* Recebe os mesmos insumos do `/simulations` (a simulação é determinística pela semente) e devolve μ, σ², ES 99%, perdas de stress, *n*_Kelly, *n*_teto, tamanho e regra (`kelly`, `cap`, `tie`, `zero` com motivo) | §7.7 |
| Operações | `GET/POST /positions` · `POST /positions/{id}/entries` · `GET /positions/{id}` (marcações, atribuição). *(1.9)* Etapa 6: `POST /positions` (insumos + `base_config_version_id`; 409 se a configuração mudou, 422 sem semáforo ou sem `override_reason` quando exigido), `GET /positions` e `GET /positions/{id}` (retrato); lançamentos, marcações e atribuição na Etapa 7. *(1.10)* `POST /positions/{id}/entries` (insumos; 422 com o motivo das validações RS-06; enfileira `marks_recompute`); `GET /positions?status=` com P&L acumulado, razão do CS-04 e sinal de erro; `GET /positions/{id}` com lançamentos (estornos ligados), quantidades atuais, marcações, atribuição diária e acumulada, banda de delta e aviso de vencimento; `POST /positions` aceita `roll_from` e devolve os limites pró-forma | §7.10 |
| Carteira e risco | `GET /portfolio` (Greeks, exposição por vencimento) · `POST /portfolio/stress` · `GET /portfolio/limits`. *(1.10)* `GET /risk/crisis` (medições por ativo e episódio, com origem) · `POST /risk/crisis/measure` (enfileira `crisis_measure`; 202) | §7.8 |
| Alertas | `GET /alerts` · `PATCH /alerts/{id}`. *(1.11)* `GET /alerts?state=&position_id=&kind=` (padrão: não resolvidos; ordem: ativos primeiro, depois a data do disparo) com o detalhe, os rótulos e a configuração do disparo; `PATCH /alerts/{id}` {`state`: `seen` ou `resolved`, `note`} (409 se já resolvido, 422 em transição inválida). `GET /positions/{id}` passa a trazer o estado de cada regra da §5.10 (ok, disparada, desligada, indisponível com o motivo), o edge da posição com intervalo e a rolagem avaliada | §7.9 |
| Performance | `GET /performance` (líquido de custos; líquido de IR separado) · `GET /performance/aggregate` | RF-DIA-05..07 |
| Configuração | `GET /config` (vigente, com os padrões preenchidos) · `POST /config` (cria versão; 422 com o campo inválido) · `GET /config/versions` (lista com nota e data) · *(1.8)* `GET /config/versions/{id}` | §7.11 |

Regras do contrato:

- **O Pydantic é a autoridade de validação.** O Zod gerado serve para dar resposta rápida na tela, e o front sempre trata erros 422 do engine.
- Mudar o contrato exige regenerar `packages/api-types` no mesmo commit (o CI verifica, §10.4).
- Endpoints de cálculo (`/simulations`, `/sizing`, `/portfolio/stress`) não gravam nada. A gravação acontece só em `POST /positions`, que recalcula no servidor e grava o retrato da decisão. O cliente não pode impor números calculados.

---

## 8. Front-end

### 8.1 Rotas e estratégia de renderização

Regra geral: **Server Components para a casca e para telas de leitura que só mudam após uma coleta; Client Components com TanStack Query para tudo que é interativo, que recalcula com entradas do usuário ou que acompanha progresso.** O cache do Next (Cache Components) **não é ativado na fase 1**: os dados mudam por ação do engine e são buscados sem cache.

| Rota | Tela | Renderização | Motivo |
|------|------|--------------|--------|
| `/` | Landing (atual) | Server + client para o 3D | Já existe |
| `/entrar` | Redireciona para `/app` | Server (redirect) | ADR-13 |
| `/cadastro` | "Em breve" | Server | ADR-13 |
| `/app` | Painel: pendências de coleta, alertas, resumo da carteira | Server (casca) + TanStack Query (pendências e alertas) | O estado muda após a coleta. *(1.11)* Lista de alertas não resolvidos (tipo com cor **e** texto, operação, regra em texto, valor × limiar, pregão, "não calibrado"), com "marcar como visto" e "resolver" (nota opcional); invalidada ao fim da coleta e de cada lançamento |
| `/app/coleta` | Execução, progresso, relatório de lacunas | TanStack Query (polling do progresso) | Progresso ao vivo |
| `/app/ranking` | Ranking com semáforo | TanStack Query | Invalida após coleta ou mudança de configuração. *(1.8)* TanStack Table; estado e direção com cor **e** texto; intervalo do edge; rótulos "não calibrado" (*s*, limiar), "estimativa" (spread) e "aproximado" (fallback); linha expandida com os custos discriminados e o motivo de "indisponível"; link para o ativo |
| `/app/ativos` | *(1.6)* Lista dos ativos cadastrados, com link para cada um | TanStack Query | Navegação até a tela do ativo antes do ranking (Etapa 5) |
| `/app/ativos/[ticker]` | RV, IV, smile, estrutura a termo, eventos, salto | Server (casca) + Client para dados e gráficos | Leitura; Plotly só no cliente |
| `/app/simulador` | Simulação, preços manuais, dimensionamento, registro da entrada | TanStack Query (mutations) + RHF/Zod | Recalcula com entradas. *(1.9)* Aberta com `?ticker=` a partir do ranking e do ativo; estrutura, vencimento e strikes (com sugestão); preços manuais com rótulo; semáforo e edge da estrutura no topo (PRD-UI-01); payoff (vencimento e datas intermediárias), Greeks, custos discriminados, histograma do P&L com média, ES 99% e percentis; painel de dimensionamento com Kelly, teto, tamanho e regra (PRD-UI-09); formulário de registro com `override_reason` quando exigido e o retrato gravado ao fim. *(1.11)* Modo rolagem (`?roll_from=`): mostra a posição de origem, preenche estrutura, ativo e destino, pede preço e custos de fechamento por perna aberta e envia `roll_from` no registro |
| `/app/carteira` | Greeks, exposição, stress, limites | TanStack Query | Stress configurável na tela. *(1.10)* Greeks totais e por ativo; exposição por vencimento; tabela de stress com os cenários de crise (origem "aproximado"/"manual"); cenário avulso; limites com estado, uso e "não calibrado"; aviso de marcações de datas diferentes |
| `/app/operacoes/[id]` | Detalhe, lançamentos, marcações, atribuição | Server (leitura) + formulário de lançamento em Client | Misto. *(1.10)* Retrato da decisão; quantidades atuais; formulário (RHF + Zod) por tipo, com estorno e motivo; marcações com rótulos "aproximado"/"desatualizado"; atribuição diária e acumulada (barras empilhadas com o **resíduo sempre visível**, execução e custos à parte), razão do CS-04 e dias com sinal de erro; indicador de banda de delta. *(1.11)* Painel "Gestão" com o estado de cada regra (§5.10), o edge da posição com intervalo, os alertas da operação e, com rolagem sugerida, o botão que abre o simulador com a rolagem preenchida |
| `/app/diario` | Lista de operações | Server + TanStack Table no cliente | Leitura. *(1.10)* Status, ativo, estrutura, direção, entrada, P&L acumulado, razão do CS-04, sinal de erro, aviso de vencimento pendente |
| `/app/performance` | Previsto × realizado, análise agregada, IR | Server + Client para gráficos | Leitura |
| `/app/modelos` | Erro de previsão por modelo × baselines | Server + Client para gráficos | Leitura; *(1.7)* seletor de ativo e horizonte, tabela com n, viés, MAE, RMSE e razão contra os baselines (com intervalos e "dados insuficientes"), previsão atual de cada modelo com intervalo, gráfico previsto × realizado por janela e escolha do modelo em uso (RF-PRV-04) |
| `/app/eventos` | Calendário e cadastro manual | TanStack Query + RHF/Zod | CRUD |
| `/app/configuracoes` | Parâmetros e histórico de versões | TanStack Query + RHF/Zod | CRUD versionado. *(1.8)* Formulários de `costs` e `edge` (taxas da B3 marcadas "a conferir") e dos parâmetros principais de `vol` e `forecast`; demais blocos só leitura; histórico com nota, data e diferenças em relação à versão anterior. *(1.11)* Formulário do bloco `management` (campos desligáveis para tempo, meta e stop, com o aviso da regra G2 no stop) e a banda de hedge exibida como a da simulação |

### 8.2 Requisitos de interface

| ID | Requisito | BRD |
|----|-----------|-----|
| PRD-UI-01 | Toda tela de decisão mostra o **número de edge e o semáforo**, não só gráficos. | PR-01 |
| PRD-UI-02 | Valores com `origin ≠ observed` têm marcação visual e tooltip explicando a origem. | PR-05 |
| PRD-UI-03 | **A formatação de unidades fica num módulo único** (`lib/format`). Componentes não formatam número por conta própria (regra de lint). | RN-PRC-04 |
| PRD-UI-04 | Gráficos de prêmio de vol e de previsão exibem **bandas do intervalo de confiança**. | PR-03 |
| PRD-UI-05 | Pontos estimados ou desatualizados têm marcação visual própria. **Lacunas aparecem como quebra na linha** (`connectgaps: false`), nunca interpoladas silenciosamente. | PR-03, LC-05 |
| PRD-UI-06 | Plotly: import dinâmico com `ssr: false`, pacote parcial só com os traços usados (scatter, bar, histogram, heatmap). A superfície 3D, opcional e fora do núcleo, carrega sob demanda. | — |
| PRD-UI-07 | Smile por vencimento e estrutura a termo em 2D são prioridade. A superfície 3D de IV é **opcional**. | RF-VOL-05 |
| PRD-UI-08 | "Dados insuficientes" e "indisponível" são estados visuais explícitos, com o motivo. | RN-PRV-02, RN-VOL-05 |
| PRD-UI-09 | A tela de dimensionamento indica qual regra prevaleceu (Kelly ou teto) e mostra zero com explicação quando não há edge líquido. | RN-SIZ-04/05 |
| PRD-UI-10 | Os alertas aparecem no painel ao abrir e após cada coleta. Não há notificação externa. | §7.9 |
| PRD-UI-11 | Aviso permanente no relatório de performance: "N = 20 valida o processo, não é evidência de edge". | §9, RS-09 |

---

## 9. Requisitos por módulo (rastreabilidade)

| Módulo | Requisitos BRD | Componentes | Aceitação (resumo) |
|--------|----------------|-------------|--------------------|
| M1 Dados | RF-DAD-01..07, RN-DAD-01..03 | `data/` (adaptadores B3 negócios, B3 COTAHIST, BCB, Yahoo), `jobs/`, `/collection` | Coleta retomável e idempotente; reprocessar a partir de `data/raw/` gera o mesmo resultado; relatório de lacunas por ativo e data; R4 confere com o COTAHIST nas fixtures (OHLC e nº de negócios). |
| M1 Vol | RF-VOL-01..05, RN-VOL-01..09 | `quant/vol`, `quant/pricing`, `jobs/` (recálculo pós-coleta) | Os 6 estimadores (§5.5) e a IV passam nos testes de referência (§10.2); retornos ajustados por proventos; pregão intradiário incompleto fora da janela; prazo constante "indisponível" sem extrapolação. |
| M1 Previsão | RF-PRV-01..04, RN-PRV-01/02 | `quant/forecast` | EWMA, combinação de estimadores e **GARCH(1,1)** (biblioteca `arch`, retornos diários ajustados, previsão agregada no horizonte); avaliação apenas com janelas não sobrepostas; baselines RV C2C 20d e IV; GARCH instável ou sem convergência → "indisponível" com motivo (LC-04). |
| M2 Eventos | RF-EVT-01/02, RN-EVT-01..03 | `/events`, `quant/events` | Salto pela estrutura a termo, conferido com o histórico; intervalo largo com pouco histórico. |
| M3 Ranking | RF-RNK-01/02, RN-EDG-01..07, RN-CST-01..03 | `quant/edge`, `quant/costs`, `/ranking` | Prêmio absoluto e edge relativo descontados do spread normal (§5.6); ranking pelo edge relativo líquido; semáforo de 3 estados com custos conservadores; limiar e spread normal rotulados "não calibrado" sem histórico. |
| M4 Simulador | RF-SIM-01..05 | `quant/simulation`, `/simulations` | Payoff, Greeks e custos para as 3 estruturas *(1.9: 5, com as compradas)*; distribuição por bootstrap considerando a regra de hedge (QA-10, §5.8). |
| M5 Dimensionamento | RN-SIZ-01..06 | `quant/sizing`, `/sizing` | Kelly 1/4 sobre o limite inferior do edge e a variância simulada; teto de 7%; zero sem edge líquido. |
| M6 Carteira e risco | RF-RSK-01..04 | `quant/risk`, `/portfolio` | Greeks agregados; 4 cenários de stress configuráveis; limites com alerta. |
| M7 Gestão | RN-GES-01..05 | `quant/rules`, `/alerts` | Alertas de hedge (banda e tempo), saída (edge relativo líquido acabou e opcionais), rolagem só com edge líquido após custos, limites, data ex-provento com posição aberta (RS-07). |
| M8 Diário e performance | RF-DIA-01..07, RN-CST-04 | `quant/attribution`, `/positions`, `/performance` | Atribuição com resíduo sempre visível; previsto × realizado nos dois níveis; IR separado. |
| M9 Avaliação de modelos | RF-PRV-03/04, CS-03 | `/models/evaluation` | Todos os modelos ativos comparados aos baselines, com nº de observações. |

Validações de consistência do diário (RS-06): quantidade resultante nunca negativa sem posição vendida correspondente; todo ajuste, exercício ou designação ligado a uma posição aberta; **resíduo da atribuição acima do limite do CS-04 gera alerta de possível erro de lançamento**.

---

## 10. Estratégia de testes

### 10.1 Pirâmide

| Camada | Ferramenta | Foco |
|--------|-----------|------|
| Motor quantitativo | pytest e hypothesis | Testes de referência obrigatórios, propriedades e unidades. **Maior peso.** |
| Ingestão | pytest com **ZIPs reais da B3** (negócios e COTAHIST) em `tests/fixtures/` | Parsing (`;`, vírgula decimal, ZIP, layout fixo do COTAHIST), regra R4 (cancelamento de 06/11/2026, negócio de D-1, sessão 6), arquivo vazio de feriado, idempotência. |
| API | pytest com Postgres de teste (container) | Contratos, validação, gravação do retrato da decisão. |
| Front | Vitest e Testing Library | `lib/format`, estados "dados insuficientes", "estimado" e "manual", formulários. |
| Ponta a ponta | Playwright | 3 fluxos críticos (§10.3). |

### 10.2 Testes de referência obrigatórios do motor

No lugar de uma meta de cobertura percentual, **a etapa não fecha sem estes testes passando**:

| # | Teste | Critério |
|---|-------|----------|
| T-REF-01 | **Black-Scholes** contra valores de referência publicados (inclusive com dividendos discretos) | erro < 1e-8 |
| T-REF-02 | **Ida e volta da IV**: preço(σ) → IV → σ, em grade de moneyness, prazos e vols (hypothesis) | erro < 1e-6 onde a vega é relevante; falha explícita (sem número) onde não há solução |
| T-REF-03 | **Paridade put-call** com dividendos discretos | resíduo < 1e-8 |
| T-REF-04 | **Greeks contra diferenças finitas** (delta, gamma, theta, vega) | tolerância relativa por Greek, documentada |
| T-REF-05 | **Estimadores de vol (os 6 do §5.5, com as duas formas de close-to-close) contra cálculo independente**: implementação ingênua em loop, planilha de referência e casos da §7 da referência técnica (inclui `bias_b` e `bias_b_zero_mean`: N = 5, 20, 100 → 0,951533; 0,987583; 0,997503); mais propriedade em série sintética (movimento browniano geométrico com σ conhecido, sem drift e sem gap): todos convergem para σ dentro de tolerância estatística documentada | erro < 1e-10 (referência); tolerância documentada (sintético) |
| T-REF-06 | **Unidades e escalas**: vol decimal × %, dias úteis × corridos, anualização 252, taxa exponencial; nenhuma função aceita ou devolve % | testes dedicados no engine e no `lib/format` |
| T-REF-07 | **Kelly e teto** em casos montados à mão (prevalece Kelly; prevalece teto; zero sem edge). *(1.9)* Também: empate (`tie`), zero por direção oposta e por μ ≤ 0, ES 99% e perdas de stress × cálculo manual, arredondamento para baixo em lotes inteiros | igualdade exata |
| T-REF-08 | **Atribuição de P&L**: em série sintética gerada pelo próprio modelo, o resíduo tende a zero. *(1.10)* Caminhos de MBG com IV constante e com IV em passeio aleatório pequeno, marcados pelo próprio BS: razão do CS-04 < 0,15 no passo diário e decrescente quando o passo diminui (ordem documentada); com IV e S fixos, só theta (resíduo ≈ 0); invariante mercado + execução = P&L pelos fluxos de caixa (exato em `Decimal`) | resíduo < limite |
| T-REF-09 | **Avaliação de modelos**: janelas não sobrepostas verificadas (nenhum dia compartilhado). *(1.7)* Também: espaçamento de *h* pregões e ancoragem no fim; nenhuma previsão usa dado posterior à origem (perturbar o futuro não muda a previsão); EWMA × laço ingênuo; previsão do GARCH × eq. 4.9 da referência e vol de longo prazo do caso MSFT (≈ 0,142); recuperação dos parâmetros do GARCH em série sintética; métricas × cálculo manual; cobertura do intervalo χ² em simulação | propriedade (hypothesis) e referência |

*(1.8)* Testes da Etapa 5 (critério de saída do PLANO, complementam os T-REF): semáforo nos três estados, nas duas direções e **nos limites** (*p*_lo = N_v e *p*_hi = −N_c não dão edge líquido; indisponível sem cada insumo), com hypothesis para a monotonicidade (subir custos ou *L* nunca melhora o estado); `leland_vol` × caso da §7 da referência (σ = 10%, meio spread 0,5%, Δt = 1/365, vendido ≈ 0,159); estimador de spread × cálculo manual e piso de tick; *s* × mediana manual e o corte de 8 pares ("não calibrado"); custos em pontos × straddle montado à mão; unidades (nada em %). Web: rótulos "não calibrado", "estimativa" e "aproximado"; Playwright: ranking → ativo, e editar um custo cria versão e muda o ranking.

*(1.9)* Testes da Etapa 6: T-REF-07; reescala do bootstrap (média 0 e desvio σ̂_d exatos; forma preservada); determinismo pela semente; propriedade: com custo zero e banda estreita, a média do P&L de um straddle ATM hedgeado tende a 𝒱·(IV − σ̂) (tolerância estatística documentada) e o desvio cai com a banda (eq. 7.7, ordem de grandeza); regra de banda × `rehedge` da referência; covered call sem ajustes; payoff no vencimento × intrínseco à mão; IV da perna manual em ida e volta; semáforo da estrutura × §5.6.1; registro recusado sem semáforo e sem `override_reason`; retrato e tabelas imutáveis (UPDATE/DELETE falham, inclusive pelo papel da aplicação); unidades (nada em %). Performance: 10.000 caminhos em < 3 s (PRD-NF-06). Playwright: fluxo 2.

*(1.10)* Testes da Etapa 7: T-REF-08; cada validação RS-06 recusando com o motivo (troca de sinal, `exit` acima do aberto, exercício de perna vendida, designação de perna comprada, europeia antes do vencimento, data antes da entrada, estorno de `entry`/`void`/já anulado, estorno que quebra lançamento posterior); estorno restaura as quantidades; exercício e designação somando só custos no vencimento; status derivado e aviso de vencimento pendente; ordem de fallback da marcação (IV de referência → fechamento "aproximado" → anterior "desatualizado"); atribuição × cálculo à mão num caso de dois pregões com provento e lançamento no dia; razão do CS-04 e sinal de erro nos limites (igual ao limite não dispara); stress por reprecificação × cálculo à mão; limites nos três estados e nos limites (comparação estrita), pró-forma exigindo `override_reason`; medição da crise com fixtures reais reduzidas dos COTAHIST de 2017 e 2020 (só as linhas dos 3 ativos e das suas opções nos episódios, com SHA-256), incluindo o fallback na RV; teto com e sem crise; idempotência do `marks_recompute`; tabelas imutáveis pelo papel da aplicação; unidades (nada em %). Web: formulário de lançamento por tipo, rótulos e resíduo sempre visível. Playwright: fluxo 3.

*(1.11)* Testes da Etapa 8 (critério de saída do PLANO: cada regra **nos limites**; alertas gravam `config_version_id`): banda (Δ igual à borda não dispara, um passo acima dispara; ajuste sugerido leva até a borda); tempo desligado por padrão e, ligado, disparando em *N* e não em *N* − 1, com hedge estornado não contando; `exit_edge` com edge pontual = 0 disparando e levemente positivo não, × cálculo à mão num straddle vendido e num comprado (custos de manter e de fechar discriminados), indisponível sem IV, σ̂ ou custos e com *h* < 1; `exit_dte` em 5 e não em 6; meta e stop desligados por padrão e, ligados, nos limites, com P&L esperado ≤ 0 indisponível; rolagem sugerida só com edge líquido depois dos custos de fechar (caso montado em que o destino tem edge sem esses custos e perde com eles), destino = primeiro vencimento com ≥ 10 du, "sem destino" com o motivo; limites espelhando `/portfolio/limits` (igual ao limite não dispara); provento na borda da janela (data ex em *t* + 5 du dispara, em *t* + 6 não, em *t* não); ajuste de strike pendente resolvido pelo lançamento e reaberto pelo estorno dele; ciclo de vida (deduplicação por chave, atualização sem mudar o estado, resolução automática com o motivo, resolução pelo usuário sem reabertura enquanto a condição durar, alerta novo quando volta, posição encerrada resolve tudo); `config_version_id` do disparo × `evaluated_config_version_id` depois de mudar a configuração; idempotência do `alerts_evaluate`; papel da aplicação sem DELETE e colunas do disparo protegidas; unidades (nada em %). Web: lista de alertas com rótulos e ações, painel "Gestão" com os quatro estados, modo rolagem do simulador. Playwright: fluxo 3 com o alerta persistente.

### 10.3 Fluxos ponta a ponta (Playwright)

1. **Coleta:** painel mostra pregões pendentes → disparar coleta (fonte simulada por fixture) → progresso → relatório de lacunas. Roda numa stack própria (`docker-compose.e2e.yml`, projeto `vollab-e2e`: banco e cache bruto separados, `DATA_SOURCE=fixtures`, "hoje" fixo em 20/11/2026). Contra um engine com fonte real o teste é pulado, para nunca disparar downloads da B3.
2. **Decisão de entrada:** ranking → ativo → simulador com preço manual → dimensionamento → registrar entrada → o retrato gravado contém semáforo, configuração e modelo.
3. **Vida da operação:** lançar hedge → marcação D-1 → atribuição com resíduo visível → alerta de banda de delta. *(1.10)* Na Etapa 7 o último passo é o **indicador** "fora da banda" na operação; o alerta persistente entra no fluxo na Etapa 8. *(1.11)* Na Etapa 8 o fluxo continua: o alerta `hedge_band` aparece no painel → marcar como visto → lançar o hedge que leva o delta até a borda → o alerta resolve sozinho depois da nova marcação. *(Ajuste na implementação, 2026-11-24)* Em vez de um pregão a mais nas fixtures (que mudaria "hoje" e os números dos fluxos 1 e 2), a entrada do fluxo 3 é registrada pelo simulador com execução em 17/11, o que dá três pregões de marcação (17, 18 e 19/11) com os dados reais já salvos; o fluxo termina encerrando a operação. Os fluxos rodam num único worker do Playwright (compartilham a configuração vigente do engine).

### 10.4 CI (GitHub Actions, a cada push)

| Job | Falha quando |
|-----|--------------|
| `web-lint-types` | ESLint ou `tsc --noEmit` com erro |
| `web-unit` | Vitest falha |
| `engine-lint-types` | ruff ou mypy com erro |
| `engine-tests` | qualquer pytest falha, **incluindo os T-REF** |
| `contract-drift` | o código gerado a partir do OpenAPI atual **diverge** do versionado em `packages/api-types` |
| `e2e` | Playwright falha (compose com Postgres e engine) |

Nenhum teste de CI acessa a B3, o BCB ou o Yahoo. As fontes externas são simuladas por fixtures.

---

## 11. Requisitos não funcionais

| ID | Requisito |
|----|-----------|
| PRD-NF-01 | **Execução local:** o Next.js (`dev` e `start`), o engine e o Postgres escutam apenas em `127.0.0.1`. Sem CORS aberto. Web e engine recusam requisições com `Host` (ou `X-Forwarded-Host`) não local, contra DNS rebinding. *(Esclarecido em 2026-11-22 pela revisão de segurança da Etapa 1: o padrão do Next é `0.0.0.0`.)* |
| PRD-NF-02 | **Coleta educada:** ritmo de requisições configurável (padrão 1 req/s), backoff exponencial, `User-Agent` genérico, sem paralelismo agressivo (RS-08). |
| PRD-NF-03 | **Coleta idempotente e retomável:** reexecutar não duplica negócios; uma interrupção retoma do último item pendente. |
| PRD-NF-04 | **Volume da carga inicial (medido na Etapa 0, filtro padrão):** universo inicial **BOVA11, BBAS3 e PETR4** → 2 COTAHIST anuais (OHLC de 1 ano) + 63 COTAHIST diários + ~190 requisições intradiárias do ativo-objeto (3 × 63) + **~17.700 de opções** (filtro: 2 mensais, K/S 0,9–1,1, ≥ 20 negócios; ~280 séries elegíveis por pregão: BOVA11 ~121, PETR4 ~100, BBAS3 ~61). A 1 req/s, **cerca de 5,0 h**. Coleta diária: **~285 requisições (~5 min)**. Comparação: ≥ 10 negócios → ~18.700 (5,3 h); ≥ 51 → ~15.100 (4,3 h, com perda nas asas e no 2º vencimento). O limiar de 20 retém 99,8% dos negócios do limiar de 10. Referência para 10 ativos: ~45 mil requisições (~12,5 h). A carga roda em várias sessões e começa pelos COTAHIST e pelo ativo-objeto. |
| PRD-NF-05 | **Segurança dos arquivos baixados:** ZIPs são tratados como entrada não confiável (limite de tamanho descompactado, sem caminhos fora do diretório de destino, só CSV aceito). Nomes de arquivo em `data/raw/` são gerados pelo engine e nunca vêm da resposta. |
| PRD-NF-06 | **Desempenho:** ranking de 10 ativos em < 2 s depois dos recálculos pós-coleta; simulação com 10.000 caminhos em < 3 s; telas de leitura em < 1 s localmente. Recálculos pesados rodam no worker depois da coleta, não na requisição. |
| PRD-NF-07 | **Bundle:** Plotly fora do bundle inicial; a landing não carrega código do cockpit. |
| PRD-NF-08 | **Backup:** script de `pg_dump` mais cópia de `data/raw/`; procedimento de restauração documentado e testado uma vez. |
| PRD-NF-09 | **Segredos:** nenhum segredo no repositório; `.env` fora do git e `.env.example` versionado. |
| PRD-NF-10 | **Logs estruturados** (structlog) com id de execução da coleta; erros de fonte externa nunca derrubam a coleta inteira. |
| PRD-NF-11 | **Reprodutibilidade:** dado um retrato de decisão, o engine consegue recalcular e comparar (mesma versão de configuração e de engine). |

---

## 12. Etapa 0 — pesquisa e validação (antes de qualquer módulo)

Objetivo: fechar as premissas e questões que podem mudar o escopo. Entregável: `docs/pesquisa/etapa-0.md` com evidências e fixtures reais salvas.

| Item | Pergunta | Critério de saída |
|------|----------|-------------------|
| PM-01 / PM-02 | O endpoint `rapinegocios` responde para ativo-objeto **e para tickers de opção individuais**? Qual formato (CSV ou ZIP)? Existe limite de ritmo? | Respostas reais salvas para pelo menos 2 ativos e 5 séries, em 3 datas. |
| QA-01 / RS-03 | Fonte oficial do cadastro de séries (código, ativo-objeto, vencimento, strike, tipo, estilo, ajustes) | Fonte escolhida e validada contra pelo menos 20 séries, ou plano B documentado. |
| QA-02 | Fonte do calendário de feriados B3 | Fonte escolhida, com os feriados de 2025–2027 conferidos. |
| QA-13 | Tratamento de `AcaoAtualizacao` e `TipoSessaoPregao` | Regras escritas e validadas contra o OHLC oficial de pelo menos 1 ativo em 10 pregões. |
| QA-04 / QA-05 | Preço de referência por série; janela de sincronização com o ativo | Proposta com evidência dos dados reais. |
| QA-06 | Filtros mínimos de liquidez | Distribuição observada de negócios por série; proposta de limiares padrão. |
| RS-02 | yfinance devolve dividendos e JCP dos ativos-alvo? | Testado; lacunas listadas. |
| PRD-NF-04 | Volume real de séries relevantes por ativo | Estimativa refinada do tempo de carga inicial. |

**Resultado (2026-11-22):** todos os itens respondidos; PM-02 validada. Relatório aprovado: [`docs/pesquisa/etapa-0.md`](./pesquisa/etapa-0.md).

**Decisão de seguir ou não:** se PM-02 falhar (o endpoint não aceitar tickers de opções), o PRD e o BRD são revisados **antes** da Etapa 1.

As questões QA-03, QA-07..QA-12 são resolvidas na etapa do módulo correspondente (ver PLANO.md), com a decisão registrada no STATUS.md.

---

## 13. Ordem de entrega

O detalhamento, com entregáveis e critérios de saída, está em [`PLANO.md`](../PLANO.md).

| Etapa | Conteúdo |
|-------|----------|
| 0 | Pesquisa e validação (§12) |
| 1 | Fundação: monorepo, migração para TS, compose, esqueleto do engine, banco, contrato gerado, CI, `lib/format`, `/entrar` e `/cadastro` |
| 2 | Dados: coleta sob demanda, cache bruto, séries, OHLC, Selic, feriados, proventos, relatório de lacunas |
| 3 | Volatilidade: RV (6 estimadores, barras de 5 min), IV, smile, estrutura a termo, prazo constante, eventos e salto, tela do ativo |
| 4 | Previsão de RV e avaliação de modelos |
| 5 | Custos, edge, semáforo, ranking, configuração versionada |
| 6 | Simulador e dimensionamento |
| 7 | Diário, marcação D-1, atribuição de P&L, carteira, stress e limites |
| 8 | Gestão da operação: alertas de hedge, saída, rolagem, limites e proventos |
| 9 | Performance, previsto × realizado, análise agregada, endurecimento e E2E completos |

---

## 14. Questões em aberto deste PRD

| ID | Questão | Quando resolver |
|----|---------|-----------------|
| PRD-QA-01 | O Hey API gera Zod e hooks do TanStack Query de forma estável a partir do OpenAPI do FastAPI? | **Resolvida na Etapa 1 (2026-11-22):** sim. `@hey-api/openapi-ts` 0.99 gera tipos, Zod, SDK com validação de resposta e `queryOptions` do TanStack Query; saída determinística (verificada pelo `contract-drift`). Plano B não usado. |
| PRD-QA-02 | Particionar `trades` por mês é suficiente para o volume real? Dados da Etapa 0: PETR4 tem 35–97 mil negócios/dia; universo inicial ≈ 10 milhões de linhas em 3 meses (ativos) + ~2 milhões (opções). | **Resolvida na Etapa 2 (2026-11-22):** sim. Medido com 10,08 milhões de linhas sintéticas em 63 pregões: ~174 B/linha (1,05 GB de dados + 0,69 GB de índices), ~3,4 milhões de linhas e ~580 MB por mês; pruning por pregão funciona (DELETE por pregão × ticker em 24 ms, COPY de 97 mil linhas em ~0,3 s). O que importa é a **ordem da chave**: instrumento primeiro (leitura de uma série em 63 pregões: 363 ms → 3 ms). Ler negócios brutos de um ativo inteiro (4,4 milhões de linhas, ~1,2 s) não cabe numa requisição: a Etapa 3 grava agregados no worker após a coleta (PRD-NF-06). Sem retenção definida: ~8 GB/ano com 3 ativos; partições mensais permitem `DROP` barato quando ela for decidida. |
| PRD-QA-03 | Método do intervalo de confiança por métrica (bootstrap × analítico) | **Resolvida na 1.7 (Etapa 4, QA-07, 2026-11-23):** previsão — empírico pelos quantis do erro log nas janelas não sobrepostas, com fallback χ² rotulado "aproximado"; métricas de erro — bootstrap percentil; RV close-to-close e salto — χ² (§5.7). |
| PRD-QA-04 | O usuário deseja a superfície 3D de IV na fase 1? | Após a Etapa 3 (opcional) |

---

## 15. Glossário

Ver [BRD §16](./BRD.md#16-glossário). Termos adicionais:

| Termo | Definição |
|-------|-----------|
| **Engine** | Serviço Python (API e worker) que concentra regras, cálculos, coleta e acesso ao banco. |
| **Retrato da decisão** | Registro imutável das entradas e saídas do cálculo no momento de uma entrada. |
| **EstimatedValue** | Envelope padrão para valores com intervalo, origem e status (§5.2). |
| **Contract drift** | Divergência entre o OpenAPI atual e os tipos gerados versionados. |
