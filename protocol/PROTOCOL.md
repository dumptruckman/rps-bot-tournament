# RPS Bot Protocol

**Protocol version:** 1  
**Status:** Draft

This document defines the interface between a Rock–Paper–Scissors Bot Artifact process and the match runner. Tournament domain terms follow [`CONTEXT.md`](../CONTEXT.md).

A bot process is a running instance of a Bot Artifact and participates in one Match. For brevity, subsequent references to a "bot" mean that process, not the Team or Bot Artifact. For each Turn, the match runner sends the bot its current state through standard input. The bot must respond with one move through standard output.

The protocol is language-neutral and line-based.

---

## 1. Overview

Each Match consists of a fixed number of Turns. A Turn completes a Round only after both bots return valid moves; a fault can end a Turn without completing a Round.

For every turn:

1. The runner sends a three-line request to each bot.
2. Each bot responds with one line containing its move.
3. The runner validates both moves.
4. The runner determines the round result.
5. The completed moves are added to both bots’ histories.
6. The next turn begins.

A bot process remains running for the entire match.

A fresh bot process is started for each new Match, including every Match in a Series.

---

## 2. Communication channels

Bots communicate with the runner using:

- **Standard input (`stdin`)** for requests from the runner.
- **Standard output (`stdout`)** for move responses.
- **Standard error (`stderr`)** for optional debugging output.

Standard output is reserved exclusively for protocol responses.

Bots must not print logs, prompts, explanations, status messages, or other content to standard output.

All text must be encoded as UTF-8.

---

## 3. Request format

For each turn, the runner sends exactly three newline-terminated lines:

```text
<turn number>
<your move history>
<opponent move history>
```

### Line 1: Turn number

The first line contains the zero-based turn number as a decimal integer.

The first turn is:

```text
0
```

The second turn is:

```text
1
```

The turn number must equal the length of both history strings.

### Line 2: Your move history

The second line contains all moves previously made by the receiving bot, ordered from oldest to newest.

The history contains only:

- `R` for Rock
- `P` for Paper
- `S` for Scissors

When no rounds have been completed, the line contains a single hyphen:

```text
-
```

### Line 3: Opponent move history

The third line contains all moves previously made by the opponent, ordered from oldest to newest.

It uses the same format as the bot’s own history.

When no rounds have been completed, the line contains:

```text
-
```

### Request example: first turn

```text
0
-
-
```

### Request example: later turn

```text
4
RPSR
SSRP
```

In this example:

- Four rounds have been completed.
- The receiving bot played `R`, `P`, `S`, and `R`.
- Its opponent played `S`, `S`, `R`, and `P`.

The current turn’s moves are never included in either history.

---

## 4. Response format

For each request, the bot must write exactly one move to standard output:

```text
R
```

or:

```text
P
```

or:

```text
S
```

The move must be followed by a newline.

Responses are case-sensitive. Lowercase values such as `r`, `p`, and `s` are invalid.

Whitespace, explanations, and additional characters are invalid.

Valid responses:

```text
R
```

```text
P
```

```text
S
```

Invalid responses include:

```text
Rock
```

```text
r
```

```text
 R
```

```text
R P
```

```text
My move is R
```

After writing a response, the bot must flush standard output immediately.

---

## 5. Round rules

The runner resolves each completed round using the standard Rock–Paper–Scissors rules:

- Rock beats Scissors.
- Scissors beats Paper.
- Paper beats Rock.
- Identical moves result in a draw.

The bot is not sent a separate round-result message.

It can determine previous results from the two move histories.

---

## 6. Process lifecycle

The runner starts one bot process at the beginning of a match.

The process may perform initialization before responding to the first request, subject to the first-turn timeout.

The process remains running until one of the following occurs:

- The match finishes normally.
- The bot commits a protocol fault.
- The bot exceeds a resource limit.
- The bot process exits unexpectedly.
- The runner terminates the match because of an infrastructure error.

When the match ends, the runner closes the bot’s standard input and terminates the process if necessary.

Bots must not depend on state from previous matches. Each match begins in a fresh process.

---

## 7. Timing requirements

Each bot must respond within the limits configured for the tournament.

The recommended limits are:

- First move: 250 milliseconds.
- Later moves: 50 milliseconds per move.
- Total response-time budget: 2 seconds per 300-turn match.

The official event configuration may use different limits. Those limits will be published before the tournament.

Response time is measured using a monotonic clock.

The runner sends both bots their requests before waiting for either response.

A bot that exceeds a per-move timeout or its total time budget commits a protocol fault.

Bots should avoid:

- Sleeping.
- Unbounded searches.
- Expensive computation on every turn.
- Reprocessing unnecessarily large amounts of data.
- Waiting for input other than the documented request.

---

## 8. Deterministic randomness

Bots may use randomness, but all tournament behavior must be reproducible.

The runner provides each bot with a deterministic bot-visible seed through the environment variable:

```text
RPS_SEED
```

The value is an unsigned 64-bit decimal integer.

Example:

```text
RPS_SEED=123456789
```

The organizer-owned wrapper's Seed Adapter deterministically maps this value into the language's seeded random-number generator. Different language wrappers are not required to produce identical random streams.

Bots must use the organizer-provided seeded random-number generator from their language template.

Bots must not seed randomness from:

- The system clock.
- Process IDs.
- Operating-system random devices.
- Network services.
- Unspecified runtime behavior.

Given the same Bot Artifact, opponent Bot Artifact, Match configuration, bot-visible seed, wrapper, and runtime, a bot must produce the same sequence of moves.

The tournament validator may execute the same match more than once to check determinism.

---

## 9. Environment variables

The runner may provide the following environment variables:

```text
RPS_PROTOCOL_VERSION=1
RPS_ROUNDS=<number of turns>
RPS_SEED=<unsigned 64-bit seed>
```

### `RPS_PROTOCOL_VERSION`

The protocol version used for the match.

For this document, the value is:

```text
1
```

### `RPS_ROUNDS`

The total number of turns scheduled for the match.

Example:

```text
RPS_ROUNDS=300
```

### `RPS_SEED`

The deterministic bot-visible seed assigned to the Bot Artifact for the Match. Opposing Bot Artifacts are not required to receive the same seed.

Bots must not depend on undocumented environment variables.

The runner does not provide the opponent's Team name or ID, Bot Artifact identifier, ranking, or implementation language.

---

## 10. Protocol faults

Any of the following is a protocol fault:

- Returning a value other than exactly `R`, `P`, or `S`.
- Returning lowercase output.
- Returning leading or trailing spaces.
- Returning more than one move for a request.
- Printing non-protocol content to standard output.
- Failing to terminate a response with a newline.
- Failing to flush a response.
- Exceeding a response timeout.
- Exceeding the total response-time budget.
- Closing standard output unexpectedly.
- Exiting before the match finishes.
- Producing excessive output.
- Exceeding a CPU, memory, process, or filesystem limit.
- Attempting prohibited network or host access.

When a protocol fault occurs, the offending bot forfeits the match.

The runner terminates the bot process immediately because any remaining output could cause the protocol stream to become misaligned.

If both bots fault during the same request, the match is recorded as a double fault.

A Bot Artifact that faults in one Match may still participate in later Matches, subject to Tournament rules. A fresh bot process is started for every Match.

---

## 11. Standard error

Bots may write debugging information to standard error.

Standard error does not affect move parsing, but it is subject to an output-size limit.

The recommended limit is 64 KiB per bot per match.

Once the limit is reached, additional standard-error output may be discarded or treated as a resource fault.

Teams should remove verbose debugging output before final submission.

Debugging output is not guaranteed to be shown during the official tournament.

---

## 12. Resource and security restrictions

Bots execute in isolated containers with restricted resources.

The official runner may enforce limits including:

- No network access.
- A read-only root filesystem.
- A small writable temporary directory.
- A non-root user.
- CPU limits.
- Memory limits.
- Process-count limits.
- Open-file limits.
- Standard-output and standard-error limits.
- No Linux capabilities.
- No privilege escalation.
- A restricted system-call profile.

Bots must not attempt to:

- Access the internet or local network.
- Contact other bots.
- Inspect tournament infrastructure.
- Read host files.
- Access container-management sockets.
- Spawn excessive child processes.
- Consume excessive CPU, memory, disk, or output.
- Exploit the runtime, compiler, operating system, or runner.
- Interfere with other matches.

The event is a strategy competition, not a container-escape or infrastructure-security challenge.

---

## 13. Organizer-owned wrappers

Official language templates include an organizer-owned protocol wrapper.

Teams should normally implement only a strategy function similar to:

```text
choose_move(turn, my_history, opponent_history, rng) -> move
```

The exact function signature depends on the language template.

The wrapper is responsible for:

- Reading requests from standard input.
- Parsing the turn and histories.
- Constructing the seeded random-number generator through the Seed Adapter.
- Calling the team’s strategy function.
- Validating the returned move.
- Writing and flushing the protocol response.
- Reporting exceptions to standard error.

Teams must not modify or replace the official wrapper unless the event rules explicitly permit it.

During submission, the organizer may combine the submitted strategy source with a clean copy of the official wrapper.

---

## 14. Example session

The following example shows three turns from one bot’s perspective.

Runner sends:

```text
0
-
-
```

Bot responds:

```text
R
```

Suppose the opponent played `S`.

Runner sends:

```text
1
R
S
```

Bot responds:

```text
P
```

Suppose the opponent played `P`.

Runner sends:

```text
2
RP
SP
```

Bot responds:

```text
S
```

At this point, the completed history is:

- Bot: `RPS`
- Opponent: `SP?`

The third opponent move will be included in the next request after both bots have responded and the round has been resolved.

---

## 15. Conformance examples

A conforming bot must correctly handle the following requests.

### Empty histories

Input:

```text
0
-
-
```

Valid output:

```text
R
```

Any of `R`, `P`, or `S` is valid.

### One completed turn

Input:

```text
1
R
S
```

Valid output:

```text
P
```

Any of `R`, `P`, or `S` remains valid. The protocol does not require a particular strategy.

### Repeated moves

Input:

```text
5
RRRRR
SSSSS
```

Valid output:

```text
R
```

### Maximum expected history

A bot must support histories at least as long as the published match length.

For a 300-turn match, the final request contains two histories of length 299.

### End of input

After the final response, the runner may close standard input.

The bot should then exit cleanly.

---

## 16. Versioning

This document defines protocol version 1.

The runner exposes the active version through:

```text
RPS_PROTOCOL_VERSION
```

Backward-incompatible changes require a new protocol version.

Examples of incompatible changes include:

- Adding or removing request lines.
- Changing history encoding.
- Changing the response format.
- Changing turn numbering.
- Adding required acknowledgements.

Clarifications that do not change valid behavior may be made without increasing the protocol version.

During a tournament, the protocol and runner behavior are frozen before coding begins.

---

## 17. Summary

For each turn, read three lines:

```text
turn
your-history
opponent-history
```

Then print and flush exactly one line:

```text
R
```

or:

```text
P
```

or:

```text
S
```

Use the provided deterministic random-number generator, keep standard output clean, and respond within the configured time limits.
