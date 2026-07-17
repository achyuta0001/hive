## Architecture Overview
*Source: `architecture-overview.md`*

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

## Open Conflicts
None found.

## Sources
- architecture-overview.md