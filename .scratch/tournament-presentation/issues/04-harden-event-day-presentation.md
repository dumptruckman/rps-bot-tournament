# Harden the event-day presentation

Status: ready-for-agent

Priority: 2

Blocked by: 02, 03

## Parent

[Tournament Presentation](../PRD.md)

## What to build

Turn the complete live and replay paths into a dependable event-day release:
package every asset for offline use, make the shared display and organizer-phone
layouts accessible, verify supported browsers, and rehearse independent Runner
and presentation interruption and resumption.

## Acceptance criteria

- [ ] All presentation assets ship as package resources, load offline, use
  correct content types and cache behavior, and are included in the repository's
  preparation and installation verification.
- [ ] The page is usable at 1280×720 and at a 375 CSS-pixel viewport, uses text
  as well as color for state, exposes semantic standings and Fixture structure,
  has visible keyboard focus, and honors `prefers-reduced-motion`.
- [ ] Connectivity changes are announced politely, competitive updates do not
  steal focus, and hostile projection or record strings are always rendered as
  text rather than HTML.
- [ ] Pinned development-only browser automation verifies Chromium without
  adding an event-day Node or browser-network dependency; the supported Firefox
  and Safari versions receive a documented manual smoke check.
- [ ] The documented browser target is the latest two major versions at release
  time of desktop Chrome/Chromium, Firefox, and Safari.
- [ ] Event rehearsal starts the Tournament Runner and presentation as separate
  processes, interrupts and resumes each independently, and exercises running,
  phase transition, pending review, completion, and abort behavior.
- [ ] Rehearsal proves that presentation reads and restarts do not change
  Competition Record bytes, Scoreboard Projection authority, reconstructed
  Tournament state, or the Tournament Champion.
- [ ] The full Python and browser suites pass, and launch, failure, recovery, and
  supported-browser instructions are complete for an event organizer.

## Comments

This issue integrates and verifies the independently delivered live-result and
replay paths; it must not expand the first-release scope into remote hosting,
authentication, operator controls, or live per-Turn projection.
