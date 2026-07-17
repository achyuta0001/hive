## API Standards
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

## Open Conflicts
- JSON Naming Convention: api-standards.md mandates **snake_case** for JSON keys in API request and response bodies; frontend-conventions.md mandates **camelCase** for JSON keys exchanged with the backend.

## Sources
- api-standards.md
- frontend-conventions.md