# Anomaly Detection Semantics (Sprint 2.1)

## Metric identity

Metric names are canonicalized with `strip().lower()` before detector lookup, baseline access, and response construction. A metric such as `Latency`, ` latency `, and `latency` therefore shares one baseline within the same project/service detector.

## Warmup and contamination policy

A detector remains in `WARMING_UP` until it has collected at least `min_samples` candidate observations. It then compares the candidate batch with its median and excludes candidates whose percentage deviation from that median meets or exceeds `threshold_pct`. For a zero median, `threshold_abs` is used instead. If fewer than `min_samples` candidates remain, those accepted candidates are retained and warmup continues. The actual rolling/EWMA baseline is seeded only after a complete accepted batch reaches `min_samples`.

This is a robust cold-start heuristic, not a guarantee against a majority of bad or coordinated warmup samples. Detection is inactive during warmup. In particular, no statistical detector can identify a bad first sample without an external reference or prior history.

## Evaluation atomicity

Each detector protects timestamp validation, evaluation, warmup screening, and baseline mutation with one re-entrant lock. This guarantees atomic evaluation/update within one Python process. It does not coordinate multiple worker processes or hosts; PostgreSQL persistence must add transaction-level concurrency control.

## Timestamp policy

- A supplied timestamp must include a timezone offset.
- Accepted timestamps are normalized to UTC.
- The event timestamp must be strictly newer than the last accepted timestamp for that project/service/metric detector.
- Duplicate or out-of-order event timestamps are rejected with HTTP `409 Conflict` and do not change the baseline.
- A missing timestamp is assigned the current UTC time. If necessary, the process-local timestamp is advanced by one microsecond to preserve strict monotonicity.

This first version intentionally rejects late-arriving measurements rather than reordering or backfilling them. A future ingestion pipeline may introduce a bounded-lateness/reorder policy, but that must be designed explicitly.

## PostgreSQL persistence boundary

Persist the state required to resume the domain behaviour, not Python object internals:

- One baseline state per `(project_id, service_id, canonical_metric_name)`.
- Algorithm identifier and the configuration snapshot needed to interpret that state.
- For rolling average: the bounded ordered accepted sample window (or an equivalent lossless representation).
- For EWMA: the current EWMA value and accepted sample count.
- Incomplete warmup candidates only while warmup is active.
- Last accepted event timestamp as the event-time watermark.

Do not persist locks, detector instances, transient response objects, or every normal measurement as an anomaly event. Normal measurements update baseline state; confirmed anomalies create durable anomaly-event records. Baseline state and anomaly-event creation must share a database transaction with idempotency enforced before either mutation is applied.
