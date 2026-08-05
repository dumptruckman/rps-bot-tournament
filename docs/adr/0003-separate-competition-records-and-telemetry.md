# Separate competition records from operational telemetry

Competitive facts are stored in canonical deterministic Competition Records,
while timings, resource measurements, stderr, host details, and failed Match
Attempts are stored as Operational Telemetry linked by canonical identifiers.
The current Match output mixes these concerns; separating them preserves
byte-identical replay compatibility without discarding diagnostics that naturally
vary between executions.
