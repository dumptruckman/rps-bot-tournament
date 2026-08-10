# Harden the event-day presentation

Status: resolved

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

- [x] All presentation assets ship as package resources, load offline, use
  correct content types and cache behavior, and are included in the repository's
  preparation and installation verification.
- [x] The page is usable at 1280×720 and at a 375 CSS-pixel viewport, uses text
  as well as color for state, exposes semantic standings and Fixture structure,
  has visible keyboard focus, and honors `prefers-reduced-motion`.
- [x] Connectivity changes are announced politely, competitive updates do not
  steal focus, and hostile projection or record strings are always rendered as
  text rather than HTML.
- [x] Pinned development-only browser automation verifies Chromium without
  adding an event-day Node or browser-network dependency; the supported Firefox
  and Safari versions receive a documented manual smoke check.
- [x] The documented browser target is the latest two major versions at release
  time of desktop Chrome/Chromium, Firefox, and Safari.
- [x] Event rehearsal starts the Tournament Runner and presentation as separate
  processes, interrupts and resumes each independently, and exercises running,
  phase transition, pending review, completion, and abort behavior.
- [x] Rehearsal proves that presentation reads and restarts do not change
  Competition Record bytes, Scoreboard Projection authority, reconstructed
  Tournament state, or the Tournament Champion.
- [x] The full Python and browser suites pass, and launch, failure, recovery, and
  supported-browser instructions are complete for an event organizer.

## Comments

This issue integrates and verifies the independently delivered live-result and
replay paths; it must not expand the first-release scope into remote hosting,
authentication, operator controls, or live per-Turn projection.

## Answer

Added installed-resource integrity verification to preparation and package
installation, offline-safe HTTP cache behavior, responsive and accessible
browser hardening, polite connectivity recovery announcements, focus retention,
and hostile-string coverage. The pinned Chromium suite now verifies shared and
phone layouts, semantic structure, reduced motion, focus, connectivity, and
text-only rendering. The release rehearsal pauses and resumes the Runner across
separate processes, restarts presentation independently, and records unchanged
Competition Record bytes, Scoreboard Projection, reconstructed Tournament state,
and Tournament Champion. Added event-organizer recovery instructions and the
manual Firefox/Safari latest-two-major release matrix.
