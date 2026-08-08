# Prefactor the Match Runner around runtime-neutral Bot sessions

Status: resolved

Blocked by: None

## What to build

Preserve the current public host-process Match behavior while separating protocol
and scoring authority from Bot process creation. The Match Runner should operate
against a small runtime-neutral Bot session contract so a later container-backed
session can participate without duplicating Turn dispatch, response timing, move
validation, Round construction, fault handling, or scoring.

This is the enabling prefactor for the container execution work. It must make no
competitive behavior change and must leave direct host-process execution
available as the fast, explicitly insecure development path.

## Acceptance criteria

- [x] The Match Runner starts, communicates with, signals, and stops Bot Artifacts through one injectable Bot session/lifecycle boundary.
- [x] The existing host-process implementation satisfies the new boundary without changing its public command contract.
- [x] Protocol version 1 parsing, simultaneous request dispatch, response timing, completed Round construction, fault detection, and Match scoring remain owned by the Match Runner.
- [x] Existing successful, forfeit, Double Forfeit, timeout, stream-limit, and termination behavior remains covered through the public Match seam.
- [x] Per-Bot visible seeds and the existing environment contract remain unchanged in host-process mode.
- [x] Infrastructure failures raised while creating or operating a Bot session remain distinguishable from competitive Bot Artifact faults.
- [x] A contract test can supply a non-process test session without adding runtime-specific branches to the Match Runner.

## Answer

Added an injectable runtime-neutral `BotSession` lifecycle and byte-transport
contract. The Match Runner now owns protocol parsing, simultaneous Turn dispatch,
response timing, move validation, competitive faults, Round construction, and
scoring for every session implementation. The existing command-based host process
is retained as the explicitly insecure default adapter with its environment,
seed, stream-limit, and phased shutdown behavior preserved.

Added a non-process scripted session contract suite covering lifecycle ordering,
request histories, dispatch-before-read behavior, scoring, Bot Artifact
disconnects, and Infrastructure Failure propagation. Existing public Match,
host-process, seed/environment, fault, timeout, stream-limit, and termination
tests remain green.
