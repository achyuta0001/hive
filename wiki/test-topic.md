## Api Standards
*Source: api-standards.md*
# API Standards

This document defines the REST API conventions for all services at Acme
Corp. Compliance is checked during code review — deviations must be
documented with a justification.

## JSON Naming Convention

All JSON keys in API request and response bodies must use **snake_case**.
This means `user_id`, not `userId` or `UserID`.

Rationale:
- Snake_case is the dominant convention in Python (our primary backend
  language) and maps directly to Python variable names without
  transformation.
- It avoids case-sensitivity ambiguity — `userId` and `userID` are
  different keys in JSON but easy to confuse in code.
- Our logging and metrics pipelines already expect snake_case field names;
  mixing conventions breaks dashboard filters.

## HTTP Status Codes

Use standard HTTP status codes consistently:

- `200` — success (GET, PUT, PATCH)
- `201` — resource created (POST)
- `204` — success with no response body (DELETE)
- `400` — client error (validation failure, malformed request)
- `401` — authentication required
- `403` — authenticated but not authorized
- `404` — resource not found
- `409` — conflict (duplicate resource, stale version)
- `422` — unprocessable (semantically invalid, e.g. business rule violation)
- `500` — internal server error (do not expose stack traces in responses)

## Pagination

All list endpoints must support cursor-based pagination using `cursor` and
`limit` query parameters. Response bodies must include a `next_cursor`
field (null when there are no more pages) and a `total_count` field.

## Versioning

API versions are carried in the URL path: `/v1/resource`, `/v2/resource`.
Do not use header-based versioning — it is harder to test, harder to
document, and invisible in access logs.

## Architecture Overview
*Source: architecture-overview.md*
# Architecture Overview

This document provides a high-level overview of the Acme Corp system
architecture. It is intended for new engineers onboarding to the
organization and should be updated whenever a new major service or
integration pattern is introduced.

## System Boundaries

The platform is divided into four layers:

1. **Client Layer** — browser SPAs (React, Next.js), iOS app (Swift),
   Android app (Kotlin). All clients communicate with the backend
   exclusively through the API Gateway.

2. **API Gateway Layer** — a single entry point (Envoy-based) that handles
   authentication, rate limiting, request routing, and TLS termination.
   All backend services sit behind this gateway; no service is directly
   exposed to the public internet.

3. **Service Layer** — approximately 20 microservices, mostly Python
   (FastAPI) with a few Go services for latency-sensitive paths. Services
   communicate via synchronous gRPC for request/response patterns and
   asynchronous Kafka for event-driven workflows.

4. **Data Layer** — PostgreSQL (primary operational store), Redis
   (caching and session state), Elasticsearch (full-text search and log
   indexing), and S3-compatible object storage (documents and binaries).

## Deployment Pipeline

All services are deployed through a shared CI/CD pipeline (GitHub Actions +
ArgoCD). The pipeline enforces the following stages:

- **Build** — compile, run unit tests, build container image
- **Stage** — deploy to staging, run integration and smoke tests
- **Production** — canary deploy to 5% of traffic for 10 minutes, then full
  rollout if error rate and latency metrics stay within baseline

The deployment order of database migrations versus application code has
been a source of ongoing discussion between the infrastructure team and the
DevOps team — see the Deployment Guide and DevOps Notes for the two current
perspectives. A final decision has not been formalized.

## API Design

The API Gateway enforces a shared set of conventions (see API Standards for
details) including URL-based versioning, cursor pagination, and standard
HTTP status codes. The JSON naming convention (snake_case per backend
standards vs. camelCase per frontend preferences) remains an open point of
friction — a transformation layer at the gateway has been proposed but not
yet implemented.

## Observability

All services must emit structured logs (JSON format), metrics (Prometheus),
and traces (OpenTelemetry). Dashboards are built in Grafana. Alerts are
routed through PagerDuty per the On-Call Handbook escalation paths.

## Deployment Guide
*Source: deployment-guide.md*
# Deployment Guide

This document describes the standard deployment process for all production
services at Acme Corp. All teams must follow this procedure unless an
explicit exception has been approved by the infrastructure team.

## Pre-deployment checklist

Before any production deploy, the following items must be completed:

1. All CI checks on the release branch must be green.
2. A rollback plan must be documented in the deploy request ticket.
3. The on-call engineer must be notified at least 30 minutes before the
   deploy window opens.

## Migration order

Database migrations must be run **before** the new application code is
deployed. This ensures that any new columns, tables, or constraints exist
before the application attempts to use them. Running migrations first also
means that if the app deploy fails partway through, the database is already
in the correct state and a rollback-forward is simpler than undoing both
schema and code changes simultaneously.

## Post-deployment verification

After the deploy completes, the engineer must verify the following within
15 minutes:

- Health-check endpoints return 200 for all instances.
- Key business metrics (sign-up rate, checkout success) have not dropped
  below the pre-deploy baseline.
- Error tracking (Sentry) shows no new error types at elevated volume.

If any of these checks fail, initiate the rollback plan immediately —
do not attempt to hotfix in production.

## Devops Notes
*Source: devops-notes.md*
# DevOps Notes

Internal working notes from the DevOps team. These reflect practical
experience and may override the official deployment guide where they
conflict — check with the team if unsure.

## Deployment flow (as actually practiced)

Over the last 18 months we've learned the hard way that running migrations
**after** the new code is deployed avoids a whole class of outages. Here's why:

- If a migration adds a NOT NULL column without a default, and the old app
  code is still running, inserts start failing immediately. Deploying code
  first (which knows about the new column) prevents this.
- Rolling back code is fast (swap the artifact). Rolling back a migration
  is slow and sometimes impossible (data loss risk). So we want the safer
  thing — the migration — to happen last, after we're confident the new
  code is stable.
- We've had three SEV-2 incidents in the last year where "migrations first"
  was the root cause. The postmortems all recommended reversing the order.

## Hotfix protocol

For critical production fixes, the full checklist can be abbreviated:

1. Skip the 30-minute on-call notification window (but ping them after).
2. CI can be bypassed if the change is a single-line revert.
3. Post-deployment verification is still mandatory — never skip health
   checks and Sentry review, even for hotfixes.

## Environment parity

All staging deployments must mirror production deployment order exactly.
We've seen bugs that only reproduce when staging uses a different migration
order than prod. Don't let staging drift.

## Frontend Conventions
*Source: frontend-conventions.md*
# Frontend Conventions

This document covers coding standards for all browser and mobile
applications at Acme Corp. The goal is consistency across the 12+
frontend codebases maintained by different product teams.

## JSON Naming Convention

All JSON keys exchanged with the backend must use **camelCase**. This means
`userId`, not `user_id` or `UserID`.

Rationale:
- CamelCase is the standard convention in JavaScript/TypeScript (our
  primary frontend languages) and matches the ECMAScript property naming
  style used by every major framework (React, Vue, Angular).
- JavaScript destructuring works naturally with camelCase properties:
  `const { userId, createdAt } = response.data` — no translation layer
  needed.
- Our GraphQL layer already uses camelCase (per the GraphQL spec), and
  mixing conventions between REST and GraphQL endpoints creates confusion
  for frontend developers who consume both.
- We previously used snake_case on the frontend (2023-2024) and it
  required a `snakeToCamel` helper imported in every data-fetching module
  — that boilerplate was a constant source of bugs when someone forgot it.

## State Management

Applications should prefer server state libraries (React Query, SWR, Apollo
Client) over client-side state management (Redux, Zustand) for all data
fetched from the backend. Client-side stores should only hold UI-only state
(modal visibility, form drafts, theme preference).

## Error Handling

Every API call must handle three states: loading, success, and error. Error
states must show a human-readable message to the user — never dump raw
HTTP status codes or stack traces into the UI.

## Bundle Size Budget

All new frontend applications must set a bundle size budget in their CI
pipeline. The initial budget is 200KB gzipped for the main entry bundle.
Any PR that exceeds the budget must include a justification and a plan to
reduce it.

## On-Call Handbook
*Source: on-call-handbook.md*
# On-Call Handbook

This handbook covers the incident response process for all engineering
teams at Acme Corp. Every engineer who goes on rotation must read this
document before their first shift.

## Incident Severity Levels

| Level | Definition | Response time |
|-------|-----------|---------------|
| SEV-1 | Complete service outage, customer data loss, or security breach | Immediate (5 minutes) |
| SEV-2 | Major feature broken, significant customer impact | 15 minutes |
| SEV-3 | Minor issue, workaround available, limited impact | 1 business day |

## Escalation Path

When an alert fires, the on-call engineer follows this sequence:

1. **Acknowledge** the alert in PagerDuty within 5 minutes. If you cannot
   acknowledge, the alert auto-escalates to the secondary on-call.
2. **Triage** — determine the severity using the table above. If unsure, err
   on the higher severity side.
3. **Mitigate** — restore service first, investigate root cause second. A
   rollback or feature flag toggle is almost always faster than writing a
   fix live.
4. **Communicate** — post to the #incidents Slack channel with current
   status. Update at least every 30 minutes during active incidents.
5. **Hand off** — if the incident spans multiple shifts, write a detailed
   handoff note before passing to the next engineer.

## Post-Incident Process

Every SEV-1 and SEV-2 incident requires a written postmortem within 5
business days. The postmortem must be blameless and focus on process
improvements, not individual mistakes. All action items from the postmortem
must have owners and due dates tracked in Jira.

## Runbook Location

Team-specific runbooks live in the `runbooks/` directory of each service
repository. If you cannot find a runbook for an alert you're responding to,
that is itself a postmortem action item — document what you did so the next
engineer has a starting point.

## Open Conflicts
- **JSON naming convention**: Backend services (API Standards) require snake_case, while frontend applications (Frontend Conventions) require camelCase. The Architecture Overview notes this as an open point of friction, proposing a transformation layer at the gateway that has not been implemented.
- **Migration order**: The Deployment Guide states that database migrations must be run **before** new application code. The DevOps Notes describe the actual practice of running migrations **after** code deployment, citing operational safety concerns and past incidents. The Architecture Overview acknowledges an ongoing discussion between teams with no formal decision, and the DevOps Notes add that staging must mirror production order.

## Sources
- api-standards.md
- architecture-overview.md
- deployment-guide.md
- devops-notes.md
- frontend-conventions.md
- on-call-handbook.md