# Azure FinOps Copilot — PRD

## Problem Statement
Web app para consolidar custos de todas as subscriptions Azure, detectar desperdícios e responder perguntas em linguagem natural sobre gastos.

## User Personas
- **Analista Cloud (primário)** — precisa de visão consolidada rápida e recomendações defensáveis
- **Time Cloud/DevOps (secundário)** — consome dashboards e relatórios executivos

## Core Requirements (static)
1. **Ingestão multi-subscription** (Azure Cost Management + Resource Graph + Monitor) via Service Principal
2. **Dashboard de custos** — KPIs (mês/YTD/projeção), breakdowns (serviço/sub/RG/região), trend 12m, top-10, comparativo M-1
3. **Recomendações de economia** — VMs ociosas, discos órfãos, IPs órfãos, rightsizing, RIs, tags faltando, dev off-hours
4. **Chat com IA** — Claude Sonnet 5 com function-calling sobre Mongo (SSE streaming)
5. **Relatórios** — CSV (costs, recomendações) + PDF (executivo via print)

## Tech Stack
- Frontend: React + Tailwind + Recharts + Framer Motion + Phosphor Icons
- Backend: FastAPI + emergentintegrations (Claude Sonnet 5)
- DB: MongoDB (motor)
- Auth: JWT single-user (admin@finops.app / admin123 seeded)
- Segurança: Fernet-encrypted client_secret

## What's Implemented (2026-02-08)
- ✅ JWT auth + admin seed
- ✅ Service Principal config (Fernet-encrypted secret) + subscription discovery
- ✅ MOCK data generator com 4 subs, 145 recursos, ~1885 registros de custo, ~102 recomendações
- ✅ Endpoints: /auth, /costs (summary/trend/breakdown/top-resources), /recommendations (list/summary/filter), /subscriptions, /service-principal, /sync, /reports (CSV + executive)
- ✅ Chat SSE com Claude Sonnet 5 + 6 tools (function-calling sobre Mongo)
- ✅ Dashboard bento-grid dark-first com KPIs, line chart 12m, pie por serviço, bar por sub/região, top-10
- ✅ Página Recomendações com chips de categoria + cards com economia
- ✅ Página Reports com download CSV + relatório executivo imprimível
- ✅ Página Settings com formulário SP + lista de subs
- ✅ AI Copilot side drawer com streaming + tool indicators + sugestões

## What's Implemented (2026-09-08) — Fase 5
- ✅ Ingestão real Azure (`/app/backend/azure_sync.py`): SubscriptionClient + Cost Management (12m, Monthly, por ResourceId/Service/RG/Location) + Resource Graph (paginado, VMs/discos/IPs/tags) + Monitor (CPU 30d por VM). Regras reais de recomendação (idle_vm, rightsizing, orphan_disk, unused_ip, missing_tags, dev_offhours). Roda em background; se SP não configurado mantém mock; se falhar, mock preservado e status=error
- ✅ Cron da plataforma (`/app/.emergent/crons.yml`): `daily-azure-sync` 03:00 BRT → `POST /api/cron/daily-sync`; `weekly-savings-alert` seg 09:00 BRT → `POST /api/cron/weekly-alert`. Auth Bearer `WEBHOOK_CRON_SECRET`, idempotência via X-Webhook-Id (coleção `cron_runs`)
- ✅ Filtros globais (barra sticky no AppShell, `lib/filters.jsx`): subscription + período (current/previous/3m/6m/12m) → costs/summary|breakdown|top-resources|trend e recommendations(+summary). Persistem em localStorage
- ✅ Alertas webhook (`/app/backend/alerts.py`): Slack / Microsoft Teams (Adaptive Card) / Google Chat; limite configurável; `GET/PUT /api/alerts/settings`, `POST /api/alerts/test`; histórico em `alert_history`
- ✅ Settings: card de fonte de dados (mock/azure/erro), badge na sidebar, salvar SP dispara sync
- ✅ Testado: iteration_2.json 100%

## Prioritized Backlog
- P0: usuário cadastrar SP real e validar sync (permissões: Cost Management Reader + Reader + Monitoring Reader)
- P1: Recomendações acionáveis (aplicar/dismiss/snooze), moeda dinâmica no frontend (hoje fmtBRL fixo)
- P2: Azure Advisor para RI/Savings Plan reais, drill-down por recurso, PDF nativo, RBAC multiusuário

## Prioritized Backlog (antigo)

### P0 — próximo ciclo
- Substituir mock por chamadas reais a Azure SDK (`azure-mgmt-costmanagement`, `azure-mgmt-resource`, `azure-monitor-query`) — a estrutura já espera a mesma shape
- APScheduler para sync diário automático

### P1
- Filtros globais no dashboard (subscription, período, tag)
- Histórico de recomendações aplicadas (dismiss / snooze / done)
- Multi-usuário com RBAC (admin/viewer)

### P2
- Alertas por email/Slack quando economia potencial > X
- Integração real com Azure Advisor para complementar recomendações
- Comparação drill-down por resource (custo diário, últimos 30 dias)
- Dashboard exportável em PDF nativo (reportlab) ao invés de window.print

## Key Files
- `/app/backend/server.py` — FastAPI + rotas + chat SSE
- `/app/backend/mock_data.py` — geradores mockados
- `/app/backend/.env` — chaves (EMERGENT_LLM_KEY, JWT_SECRET, ENCRYPTION_KEY, ADMIN_*)
- `/app/frontend/src/App.js` — routes protegidas
- `/app/frontend/src/pages/*.jsx` — 5 páginas (Login, Dashboard, Recomendações, Reports, Settings) + ChatDrawer + AppShell
