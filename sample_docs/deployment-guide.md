---
title: Deployment Guide
author: infra-team
tags: [deployment, operations, migrations]
last-reviewed: 2025-11-15
---

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