---
title: On-Call Handbook
author: sre-team
tags: [incidents, on-call, escalation]
last-reviewed: 2025-10-01
---

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