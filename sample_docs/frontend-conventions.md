---
title: Frontend Conventions
author: ui-platform-team
tags: [frontend, javascript, api-integration]
last-reviewed: 2025-09-20
---

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