# Resume from immutable competition records

A terminal Competition Record commits a Match, while Tournament State Snapshots
are optional rebuildable caches derived from the sealed Tournament Manifest and
ordered Competition Records. Interrupted uncommitted Match Attempts restart from
Turn 0 with identical inputs; this prevents mutable snapshots from becoming a
second source of competitive truth or a mechanism for rerunning completed
Matches.
