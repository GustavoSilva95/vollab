# VolLab — contexto e regras do projeto

Cockpit de decisão para traders de volatilidade em opções na B3: mede RV × IV, diz se existe **edge líquido de custos e com intervalo de confiança**, dimensiona a posição, acompanha risco e Greeks e mantém um diário com atribuição de P&L. **Não executa ordens nem se integra a corretoras.** Fase 1: local, um único usuário, sem login.

## Regras de processo (obrigatórias)

1. **No início de cada sessão, leia `STATUS.md` e `PLANO.md`** antes de qualquer outra ação.
2. **Não comece uma etapa sem o documento anterior aprovado.** A aprovação é dada pelo usuário e registrada em `STATUS.md`. Em caso de dúvida, pergunte.
3. **Atualize `STATUS.md` ao fim de cada etapa**: o que foi feito, as decisões tomadas (QA-xx resolvidas), bloqueios e próximos passos.
4. **Não altere o escopo sem atualizar o BRD e o PRD.** Se uma tarefa exigir algo fora do PRD, pare, explique e proponha a alteração dos documentos antes de implementar.
5. Toda mudança de código deve ser rastreável a um ID do BRD ou do PRD (RF-, RN-, PRD-…). Cite o ID na descrição do commit ou do PR.
6. Antes de escrever código do Next.js, leia o guia relevante em `node_modules/next/dist/docs/` (ver o bloco no fim deste arquivo). Exemplo: no Next 16, `middleware` virou `proxy.ts`.

## Documentos-fonte (nesta ordem de autoridade)

| Documento | Papel |
|-----------|-------|
| [`docs/BRD.md`](docs/BRD.md) | O quê e por quê (requisitos de negócio) |
| [`docs/PRD.md`](docs/PRD.md) | Como: arquitetura, ADRs, dados, API, telas, testes |
| [`PLANO.md`](PLANO.md) | Etapas, entregáveis e critérios de saída |
| [`STATUS.md`](STATUS.md) | Onde estamos agora |

## Stack (resumo — detalhes no PRD §3)

- **Web** (`apps/web`): Next.js 16, React 19, **TypeScript**, CSS Modules e os tokens atuais, Radix UI, TanStack Table, TanStack Query, React Hook Form com Zod, Plotly.js (import dinâmico, `ssr: false`, pacote parcial).
- **Engine** (`services/engine`): Python 3.13, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, numpy, pandas, scipy, arch. Tem processo de API e processo de worker.
- **Banco:** PostgreSQL 17 via Docker Compose. **Só o engine acessa o banco.**
- **Contrato:** OpenAPI do FastAPI → `packages/api-types` (gerado e versionado; nunca editar à mão).
- **Testes:** pytest e hypothesis, Vitest e Testing Library, Playwright. CI no GitHub Actions.
- **Estrutura atual:** o código ainda está na raiz em JS. A migração para o monorepo e para TS é a Etapa 1.

## Convenções técnicas

- **Unidades (PRD §5.1):** vol sempre **decimal anualizada em base 252**; tempo em anos úteis (du/252); taxa decimal exponencial; dinheiro em `Decimal`/`NUMERIC`, nunca float no banco. **Percentual só em `apps/web/lib/format/`.** Campos ambíguos levam a unidade no nome (`_bd`, `_cd`).
- **Estimativas usam `EstimatedValue`** (PRD §5.2): valor, intervalo, status e origem. Amostra insuficiente → `insufficient_data`, nunca um número sem lastro. Valores estimados, manuais ou aproximados são sempre rotulados na interface.
- **Lacunas não são interpoladas em silêncio**: aparecem como quebra no gráfico (`connectgaps: false`).
- **Decisões gravadas são imutáveis** e guardam `config_version_id`, o modelo de RV e `engine_version`.
- O pacote `quant/` do engine **não faz I/O**. Fontes externas ficam atrás de adaptadores em `data/`.
- Endpoints de cálculo não gravam nada. Só `POST /positions` grava, e ele recalcula no servidor.
- Respostas da B3 e arquivos ZIP são **entrada não confiável** (PRD-NF-05).
- O engine escuta só em `127.0.0.1`. Nenhum segredo no repositório (`.env` fora do git).
- **Idioma:** identificadores de código em inglês; interface, documentação e commits em português.
- **Testes de referência T-REF-01..09 (PRD §10.2) são obrigatórios**: nenhuma etapa do motor fecha sem eles.
- Nenhum teste de CI acessa a rede externa; fontes são simuladas por fixtures reais salvas.

## Papéis (subagentes em `.claude/agents/`)

| Papel | Arquivo | Quando usar |
|-------|---------|-------------|
| Analista | `analista.md` | Refinar requisitos, rastreabilidade BRD → PRD → código, critérios de aceitação, Etapa 0 |
| Desenvolvedor | `desenvolvedor.md` | Implementar o que está no PLANO e no PRD da etapa aprovada |
| Revisor de segurança | `revisor-seguranca.md` | Ao fechar etapas que tocam entrada externa, banco, rede ou segredos |
| Revisor de performance | `revisor-performance.md` | Ao fechar etapas com cálculo pesado, consultas, coleta ou bundle |

Os revisores só leem e reportam; não alteram código.

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
