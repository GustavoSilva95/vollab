# STATUS

**Atualizado em:** 2026-11-21
**Etapa atual:** Etapa 0 — Pesquisa e validação (liberada, não iniciada)
**Próxima etapa:** Etapa 1 — Fundação (bloqueada até o relatório da Etapa 0 ser aprovado)

## Aprovações

| Documento | Versão | Situação | Data |
|-----------|--------|----------|------|
| BRD | 1.0 | Aprovado | 2026-11-21 |
| PRD | 1.0 | Aprovado | 2026-11-21 |
| Relatório da Etapa 0 | — | Não iniciado | — |

## Feito

- Landing page com a superfície de volatilidade 3D (antes do BRD).
- BRD 1.0 escrito e aprovado.
- Entrevista de arquitetura concluída. As decisões estão no PRD §3 (ADR-01 a ADR-16).
- PRD 1.0 escrito e aprovado.
- Ambiente do projeto criado: `AGENTS.md` (contexto e regras), `CLAUDE.md`, papéis em `.claude/agents/`, `PLANO.md` e este arquivo.

## Decisões registradas

| Data | Decisão | Onde |
|------|---------|------|
| 2026-11-21 | Stack: TS (web) + Python/FastAPI (engine) + Postgres/Docker; só o engine acessa o banco | PRD §3 |
| 2026-11-21 | Coleta sob demanda com recuperação de pregões pendentes, sem agendador | ADR-07 |
| 2026-11-21 | `/entrar` leva ao cockpit; `/cadastro` mostra "em breve"; modelo de dados com `user_id` | ADR-13 |
| 2026-11-21 | Testes de referência obrigatórios no lugar de cobertura percentual; CI falha com drift do contrato | PRD §10 |

## Bloqueios e riscos ativos

- PM-02 (o endpoint da B3 aceita tickers de opções) ainda não foi validado. Se falhar, o escopo muda.
- Carga inicial estimada em ~7–8 h a 1 req/s (PRD-NF-04). O número será refinado na Etapa 0.

## Próximos passos

1. Iniciar a Etapa 0 com o papel de analista.
2. Primeiro item: testar o endpoint da B3 com ativo-objeto e opções, buscar as fontes de cadastro de séries e de feriados.
