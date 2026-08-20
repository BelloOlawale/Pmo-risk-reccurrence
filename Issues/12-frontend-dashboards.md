# 12: Frontend — Scaffold + Project/Portfolio Dashboards

- **Type:** AFK
- **Spec:** SPEC.md §11
- **Blocked by:** #07, #08, #09, #10 (needs the APIs)

## What to build

React + TypeScript frontend (no SharePoint/Power BI).

1. Scaffold: Vite + React + TS, routing, API client, Entra auth (MSAL), layout + nav.
2. **Project dashboard:**
   - KPI cards (total, high, escalated, SLA compliance %)
   - donut (rating), stacked bar (status), treemap (category)
   - SLA countdown list
   - Risk Register table: conditional formatting, search + multi-column filters, sort (rating/owner/status), click → detail
3. **Risk detail page:** full info, status history timeline (from audit log), source-file citation link, acknowledge + edit actions.
4. **Portfolio dashboard:** project × category heatmap, risk-by-project bar, escalation trend line, portfolio KPIs.
5. Charts via Apache ECharts.

## Acceptance criteria

- [ ] App authenticates via Entra (MSAL)
- [ ] Project dashboard renders live data from the API
- [ ] Register table sorts/filters and drill-throughs to risk detail
- [ ] Risk detail shows audit-log history timeline
- [ ] Portfolio dashboard shows heatmap + trends
- [ ] No Power BI / SharePoint anywhere
