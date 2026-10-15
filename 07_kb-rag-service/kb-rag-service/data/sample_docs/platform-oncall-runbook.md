# Platform On-call Runbook

Applies to: platform engineering only. Owner: Platform team.

## Rota

The on-call rota is one week, Monday 10:00 to Monday 10:00. Primary and secondary
are both paged for P1 incidents. Swaps must be agreed with the other engineer and
updated in PagerDuty before the shift starts.

## Severity levels

- P1: user facing outage or data loss. Acknowledge within 5 minutes, start an
  incident channel, update the status page every 30 minutes.
- P2: degraded service, a workaround exists. Acknowledge within 30 minutes.
- P3: no user impact. Raise a ticket and handle in working hours.

## Escalation

If the primary does not acknowledge a P1 within 5 minutes, PagerDuty escalates to
the secondary. After 15 minutes it goes to the engineering manager on call.
Escalation contact for vendor issues: Jane Doe, jane.doe@example.com, 07700 900123.

## Deploy freeze

No production deploys from 18 December to 2 January unless it is a fix for a P1 or
P2 and the engineering manager signs off in the incident channel.

## Payment

On-call allowance is paid per week on the rota, plus time off in lieu for any
callout outside working hours that lasts more than one hour.
