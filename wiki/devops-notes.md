## Deployment Guide
*Source: deployment-guide.md
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
*Source: devops-notes.md
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

## Open Conflicts
- **Migration order**: The Deployment Guide states migrations must be run **before** new application code ([source: deployment-guide.md]), whereas DevOps Notes describes running migrations **after** code deployment as the practiced approach ([source: devops-notes.md]).
- **Hotfix / on‑call notification**: The Deployment Guide forbids hotfixing in production and requires the on‑call engineer to be notified at least 30 minutes before the deploy window ([source: deployment-guide.md]). DevOps Notes provides a hotfix protocol that allows skipping the 30‑minute on‑call notification window (with a follow‑up ping) and permits an abbreviated checklist for critical production fixes ([source: devops-notes.md]).

## Sources
- deployment-guide.md
- devops-notes.md