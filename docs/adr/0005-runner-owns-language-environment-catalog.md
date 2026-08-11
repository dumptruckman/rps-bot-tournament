# Make the Runner the sole Language Environment Catalog authority

Status: accepted

The RPS Tournament Runner repository is the exclusive authority for the
Language Environment Catalog and every organizer-controlled asset that gives a
Language Environment meaning: its Team Source schema, wrapper, Seed Adapter,
pinned runtimes, networkless build recipe, readiness contract, entrypoint, and
conformance fixtures. These assets are versioned and published together as a
Catalog Release.

The companion repository owns independent participant-facing Team Templates.
Each Template Release is an adapter that claims compatibility with exactly one
published Catalog Release through the interface in
`docs/CATALOG_COMPATIBILITY.md`. A compatibility claim does not transfer
authority for catalog assets to the template repository and does not make a
Team Template an input to the Runner.

The Runner repository never fetches, imports, or tests the Team Template
repository. Its validation, build, certification, preparation, Tournament,
rehearsal, and offline workflows operate solely on Team Source presented at the
local source-directory boundary plus Runner-owned inputs. Catalog conformance
fixtures are organizer certification assets, not Team Templates.

This decision supersedes the split-authority repository boundary originally
described in the Containerized Bot Environments PRD. It does not change the
accepted deterministic replay model, language-specific Seed Adapter rule,
organizer-wrapper authority, separation of Competition Records from Operational
Telemetry, resumption from immutable Competition Records, or the requirement
that a sealed Tournament's inputs remain immutable. Advisory Validation remains
non-authoritative; Final Validation remains organizer-controlled and is the only
validation that can authorize a Bot Artifact for a Tournament roster.

The consequence is one directional dependency: a Team Template may consume an
exact published Catalog Release, but the Runner never depends on a Team Template
or its repository. Catalog changes require a new Catalog Release; template
compatibility changes require a new Template Release.
