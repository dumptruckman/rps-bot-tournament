# Use versioned HMAC seed derivation

Tournament Seed derivation uses a domain-separated HMAC-SHA-256 hierarchy whose
version and derived unsigned 64-bit values are recorded with Tournament results.
This avoids runtime-specific hashes and PRNGs while making schedule, position,
Match, and bot-visible seeds reproducible; changing the derivation version is an
explicit replay-compatibility break rather than a silent behavior change.
