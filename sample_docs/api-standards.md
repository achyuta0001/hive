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