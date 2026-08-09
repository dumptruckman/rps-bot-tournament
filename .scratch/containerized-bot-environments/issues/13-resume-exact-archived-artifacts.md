# Resume with exact archived Bot Artifacts

Status: resolved

Blocked by: 12

## What to build

Carry exact Bot Artifact resolution through Tournament retries, interruption,
opening, and Step Mode resumption. Every unresolved execution boundary must
verify the selected image; a missing cache entry may be restored from the
verified archive, but no post-creation path may rebuild or substitute another
image.

An interrupted uncommitted Match Attempt restarts from Turn 0 with the same
sealed images, profile, seeds, and inputs under the existing absolute Match
Attempt policy.

## Acceptance criteria

- [x] Tournament opening verifies every sealed Bot Artifact, platform, artifact-store index, catalog, validation, and execution-profile identity.
- [x] A selected image missing from the active engine is loaded automatically from the verified archive and re-verified before execution.
- [x] A missing, corrupt, wrong-platform, or digest-mismatched artifact blocks execution as an infrastructure or integrity condition.
- [x] No retry, opening, or resumption path rebuilds from source or substitutes a mutable tag.
- [x] An interrupted uncommitted container Match Attempt restarts from Turn 0 with identical sealed images, seeds, limits, and Match inputs.
- [x] Docker and host failures use the existing absolute three-attempt retry and operator-intervention policy.
- [x] Fresh containers are used for every retry and later Match, with no Team state persisting between Matches.
- [x] Repeated runs from the same sealed inputs preserve byte-identical canonical Competition Records and equivalent reconstructed Tournament state despite telemetry differences.
- [x] Artifact loading, verification, startup, and retry diagnostics remain Operational Telemetry and cannot alter the Scoreboard Projection.

## Answer

Official Tournament reopening now derives execution exclusively from the sealed
Tournament Manifest and the integrity-verified Bot Artifact store; the draft
plan is no longer required after creation. Opening verifies the exact catalog,
execution profile and operational timeouts, target platform, artifact-store
index, canonical Bot Artifact identities, and organizer-final validation reports
under the Tournament run lock before resolving every selected image.

The archive resolver restores a missing image only with `docker image load` from
the verified local archive and rechecks its image ID, platform, retained bytes,
and authoritative digest. Resolution failures enter the existing Infrastructure
Failure telemetry contract, so later-boundary Docker failures retain the
absolute three-attempt/operator-intervention behavior without changing canonical
records or the Scoreboard Projection. Existing fresh-container cleanup and
interrupted Match Attempt behavior now have explicit coverage that all sealed
request inputs remain identical across resumption apart from the absolute
attempt number.
