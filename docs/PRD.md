# PRD — Documento de Requisitos de Produto

**Projeto:** VolLab — cockpit de decisão para traders de volatilidade em opções
**Base:** [BRD 1.4 — Fase 1](./BRD.md) (aprovado em 2026-11-22)
**Referência técnica de fórmulas:** [`referencia/volatility-trading.md`](./referencia/volatility-trading.md) — sempre a forma corrigida; nunca a forma impressa no livro de fórmula listada na Errata (§2 da referência)
**Versão:** 1.6
**Data:** 2026-11-23
**Status:** Aprovado (1.6, 2026-11-23)

> **Histórico:** 1.0 (2026-11-21) aprovado. 1.1 (2026-11-22) incorpora os resultados da Etapa 0 ([relatório](./pesquisa/etapa-0.md), alterações A-01..A-10): adaptador COTAHIST, regra R4, IV de referência, filtros de liquidez padrão, feriados com fonte/confirmação, volume de carga revisado e universo inicial de 3 ativos. 1.2 (2026-11-22): filtro de liquidez padrão de ≥ 20 negócios (QA-06) e PRD-NF-04 recalculado. 1.3 (2026-11-22, Etapa 2, aprovado): proventos do Yahoo por httpx na API de gráficos, sem `yfinance` (decisão do usuário); nomes físicos das tabelas de dados confirmados (§6); stack separada do E2E com fonte simulada (§10.3). 1.4 (2026-11-22, aprovado): estimadores de RV do BRD 1.3 (§5.5, §6.2 `intraday_bars` e `realized_vols`, T-REF-05 ampliado) e GARCH(1,1) explícito (§9). 1.5 (2026-11-22, decisão do usuário): referência técnica de fórmulas com Errata; close-to-close padrão com **média zero e divisor n** (eq. 2.1b), forma com média subtraída e *n* − 1 mantida como opção de comparação, correção de viés com `bias_b_zero_mean` (§5.5); prêmio absoluto, edge relativo e spread normal (§5.6, BRD RN-EDG-01/02/07); renumeração RN-EDG-03..06. 1.6 (2026-11-23, Etapa 3, aprovado): detalhes físicos e de método da volatilidade — `intraday_sessions` e `constant_maturity_vols` (§6.2), salto de evento e IV ex-evento calculados na leitura em vez de `event_jumps` (§6.4), `corporate_actions.event_id`, endpoints `/summary` e `/prices` e a lista `/app/ativos` (§7, §8.1), métodos da §5.5.1; nenhuma mudança de escopo do BRD.

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
- O primeiro valor de cada parâmetro marcado "a definir com o usuário" (QA-11) é preenchido na Etapa 6 e rotulado como "não calibrado".

### 5.4 Retrato da decisão (RF-DIA-01, RN-EDG-06)

Ao registrar uma entrada, o engine grava um retrato imutável (JSONB) com: semáforo, prêmio absoluto e edge relativo com intervalos, spread normal usado (e se calibrado), IV, RV prevista, modelo, custos discriminados, distribuição simulada resumida, Kelly, teto e qual dos dois prevaleceu, tamanho sugerido × executado, `config_version_id`, `engine_version` (git sha) e as entradas manuais usadas.

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
| `rv_forecasts` | previsão por modelo, ativo, data e horizonte, com intervalo | RF-PRV-01/02 |
| `forecast_evaluations` | erro por modelo e baseline, apenas janelas não sobrepostas, nº de observações | RF-PRV-03, RN-PRV-01 |

### 6.5 Configuração, operações e risco

| Tabela | Conteúdo | BRD |
|--------|----------|-----|
| `config_versions` | snapshot JSONB imutável de todos os parâmetros | §7.11 |
| `positions` | operação: estrutura, ativo, status (aberta / encerrada), retrato da decisão, `config_version_id` | RF-DIA-01 |
| `position_entries` | lançamentos tipados: entrada, hedge, ajuste de strike, exercício, designação, saída, rolagem (fechamento + abertura ligados), com preço, quantidade e custos reais | RF-DIA-02/03, RN-GES-04 |
| `daily_marks` | marcação D-1 por posição: preços, IV, Greeks | §6 do BRD |
| `pnl_attribution` | P&L diário por delta, gamma, theta, vega e resíduo | RF-DIA-04 |
| `alerts` | tipo (hedge, saída, rolagem, limite, provento), regra, posição, estado (ativo / visto / resolvido), `config_version_id` | §7.9 |
| `manual_inputs` | preços do momento e margem informados pelo usuário, com hora | RF-SIM-03, RN-SIZ-06 |

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
| Previsão | `GET /forecasts?underlying=&horizon_bd=&model=` · `GET /models/evaluation` | §7.1 Previsão |
| Ranking | `GET /ranking` | §7.4 |
| Simulação | `POST /simulations` (estrutura, séries, preços manuais opcionais) → payoff, Greeks, custos, distribuição de P&L, P&L esperado | §7.6 |
| Dimensionamento | `POST /sizing` (simulação, capital, margem manual) → Kelly, teto, tamanho final e regra que prevaleceu | §7.7 |
| Operações | `GET/POST /positions` · `POST /positions/{id}/entries` · `GET /positions/{id}` (marcações, atribuição) | §7.10 |
| Carteira e risco | `GET /portfolio` (Greeks, exposição por vencimento) · `POST /portfolio/stress` · `GET /portfolio/limits` | §7.8 |
| Alertas | `GET /alerts` · `PATCH /alerts/{id}` | §7.9 |
| Performance | `GET /performance` (líquido de custos; líquido de IR separado) · `GET /performance/aggregate` | RF-DIA-05..07 |
| Configuração | `GET /config` (vigente) · `POST /config` (cria versão) · `GET /config/versions` | §7.11 |

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
| `/app` | Painel: pendências de coleta, alertas, resumo da carteira | Server (casca) + TanStack Query (pendências e alertas) | O estado muda após a coleta |
| `/app/coleta` | Execução, progresso, relatório de lacunas | TanStack Query (polling do progresso) | Progresso ao vivo |
| `/app/ranking` | Ranking com semáforo | TanStack Query | Invalida após coleta ou mudança de configuração |
| `/app/ativos` | *(1.6)* Lista dos ativos cadastrados, com link para cada um | TanStack Query | Navegação até a tela do ativo antes do ranking (Etapa 5) |
| `/app/ativos/[ticker]` | RV, IV, smile, estrutura a termo, eventos, salto | Server (casca) + Client para dados e gráficos | Leitura; Plotly só no cliente |
| `/app/simulador` | Simulação, preços manuais, dimensionamento, registro da entrada | TanStack Query (mutations) + RHF/Zod | Recalcula com entradas |
| `/app/carteira` | Greeks, exposição, stress, limites | TanStack Query | Stress configurável na tela |
| `/app/operacoes/[id]` | Detalhe, lançamentos, marcações, atribuição | Server (leitura) + formulário de lançamento em Client | Misto |
| `/app/diario` | Lista de operações | Server + TanStack Table no cliente | Leitura |
| `/app/performance` | Previsto × realizado, análise agregada, IR | Server + Client para gráficos | Leitura |
| `/app/modelos` | Erro de previsão por modelo × baselines | Server + Client para gráficos | Leitura |
| `/app/eventos` | Calendário e cadastro manual | TanStack Query + RHF/Zod | CRUD |
| `/app/configuracoes` | Parâmetros e histórico de versões | TanStack Query + RHF/Zod | CRUD versionado |

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
| M4 Simulador | RF-SIM-01..05 | `quant/simulation`, `/simulations` | Payoff, Greeks e custos para as 3 estruturas; distribuição por bootstrap considerando a regra de hedge (QA-10). |
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
| T-REF-07 | **Kelly e teto** em casos montados à mão (prevalece Kelly; prevalece teto; zero sem edge) | igualdade exata |
| T-REF-08 | **Atribuição de P&L**: em série sintética gerada pelo próprio modelo, o resíduo tende a zero | resíduo < limite |
| T-REF-09 | **Avaliação de modelos**: janelas não sobrepostas verificadas (nenhum dia compartilhado) | propriedade |

### 10.3 Fluxos ponta a ponta (Playwright)

1. **Coleta:** painel mostra pregões pendentes → disparar coleta (fonte simulada por fixture) → progresso → relatório de lacunas. Roda numa stack própria (`docker-compose.e2e.yml`, projeto `vollab-e2e`: banco e cache bruto separados, `DATA_SOURCE=fixtures`, "hoje" fixo em 20/11/2026). Contra um engine com fonte real o teste é pulado, para nunca disparar downloads da B3.
2. **Decisão de entrada:** ranking → ativo → simulador com preço manual → dimensionamento → registrar entrada → o retrato gravado contém semáforo, configuração e modelo.
3. **Vida da operação:** lançar hedge → marcação D-1 → atribuição com resíduo visível → alerta de banda de delta.

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
| PRD-QA-03 | Método do intervalo de confiança por métrica (bootstrap × analítico) | Etapa 4 (QA-07) |
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
