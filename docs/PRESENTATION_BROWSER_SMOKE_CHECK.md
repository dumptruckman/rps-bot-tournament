# Presentation browser release record

Complete and retain one copy of this record for every release. Record the exact
installed versions; do not write `latest`. The current and immediately previous
desktop major versions at release time must all pass.

| Browser | Full version | Operating system | Tester | Date | Result |
| --- | --- | --- | --- | --- | --- |
| Chrome/Chromium current |  |  |  |  |  |
| Chrome/Chromium previous |  |  |  |  |  |
| Firefox current |  |  |  |  |  |
| Firefox previous |  |  |  |  |  |
| Safari current |  |  |  |  |  |
| Safari previous |  |  |  |  |  |

For each row, verify both a 1280×720 viewport and a 375 CSS-pixel viewport:

- [ ] waiting, paused, running, phase transition, and Match-boundary updates;
- [ ] pending organizer review, completion with and without a Tournament
  Champion, and abort;
- [ ] keyboard focus visibility and retention, replay Enter/arrow/Escape
  controls, standings table semantics, and Fixture list/headings;
- [ ] three-poll connectivity warning and polite recovery announcement;
- [ ] reduced-motion preference and no document-level horizontal overflow;
- [ ] literal hostile Team Display Name and record strings with no created HTML;
- [ ] live and replay facts remain after presentation stop and restart; and
- [ ] no request leaves the loopback presentation origin.

Attach failure notes and screenshots to this record. Any blank or failed row
blocks release support for the six-version browser target.
