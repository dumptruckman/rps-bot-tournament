# Resume with exact archived Bot Artifacts

Status: ready-for-agent

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

- [ ] Tournament opening verifies every sealed Bot Artifact, platform, artifact-store index, catalog, validation, and execution-profile identity.
- [ ] A selected image missing from the active engine is loaded automatically from the verified archive and re-verified before execution.
- [ ] A missing, corrupt, wrong-platform, or digest-mismatched artifact blocks execution as an infrastructure or integrity condition.
- [ ] No retry, opening, or resumption path rebuilds from source or substitutes a mutable tag.
- [ ] An interrupted uncommitted container Match Attempt restarts from Turn 0 with identical sealed images, seeds, limits, and Match inputs.
- [ ] Docker and host failures use the existing absolute three-attempt retry and operator-intervention policy.
- [ ] Fresh containers are used for every retry and later Match, with no Team state persisting between Matches.
- [ ] Repeated runs from the same sealed inputs preserve byte-identical canonical Competition Records and equivalent reconstructed Tournament state despite telemetry differences.
- [ ] Artifact loading, verification, startup, and retry diagnostics remain Operational Telemetry and cannot alter the Scoreboard Projection.

