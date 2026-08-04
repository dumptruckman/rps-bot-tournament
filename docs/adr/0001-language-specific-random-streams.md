# Allow language-specific deterministic random streams

Each organizer-owned language wrapper deterministically adapts the Bot
Artifact's 64-bit seed to its own random-number generator, and wrappers are not
required to produce identical streams across languages. Standard RNG seed widths
and algorithms differ, so this keeps templates idiomatic while preserving replay
through immutable, versioned wrappers and runtimes; consequently, otherwise
equivalent strategies ported between languages may make different random choices.
