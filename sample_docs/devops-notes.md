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