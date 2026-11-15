<!--
The intake artifact for the demo. Create it as a real issue in the octodemo
fork so forge-builder Phase 1 reads it the way it will in production:

    gh label create metric-request --repo octodemo/build-once-run-on-any-agent \
      --color 0E8A16 --description "Request for a new metric build" --force
    gh issue create --repo octodemo/build-once-run-on-any-agent \
      --title "Track our 48-hour dispatch promise" \
      --body-file issues/dispatch-promise.md --label metric-request

It deliberately leaves business decisions open -- whether an order that ships
late still counts as a missed promise, what happens to cancelled orders, and
which day each result is counted on -- so the agent has to ask, not guess.
-->

Operations wants to know whether we keep our dispatch promise: every order
should leave a fulfilment centre within 48 hours of being placed. Today we can
see how many orders are placed and cancelled each day, but nobody can say how
many promises we kept or broke without pulling raw data by hand.

What we need, roughly:

- For each merchant, how many orders met the 48-hour dispatch promise and how
  many missed it
- Counted per day and as a running total, like the existing order metrics, so
  the two can sit side by side on the operations dashboard
- Available for both regions (east and west)
- Please add these as Dispatch metrics next to the existing Order metrics

Things we know about the data:

- Dispatch attempts are in `dispatch_attempts`. The warehouse logs every
  attempt, so an order that failed twice before it went out has three rows.
- All timestamps are Sydney time.

Not in scope for this request: a "currently overdue" backlog view, per-region
local business days, and anything that needs carrier tracking data. Those are
follow-ups.
