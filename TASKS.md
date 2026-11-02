# E7 Shop Reroller — v1.0 Release Task Sheet

Status: planning. Check items off as they are implemented and verified.

## P0 — Automated regression tests

- [x] Add a `tests/` suite that runs offline without Epic Seven, a graphical session, or mouse input.
- [ ] Collect small, sanitized reference screenshots for Covenant, Mystic, Friendship, multiple distinct offers, duplicate same-currency offers, and sold (`0/1`) rows.
- [ ] Test detection at expected window dimensions and for adjacent shop rows.
- [ ] Test initial availability checks, `1/1` to `0/1` verification, and safe handling of ambiguous confirmations.
- [ ] Test refresh-count and Skystone limits, including 30 and 31 Skystones, final-shop scanning, and pause/resume boundaries. (Budget arithmetic covered; final-shop and pause/resume integration remain.)
- [x] Add a documented command for running tests and include them in pre-release checks.

**Distribution decision:** Keep tests, fixtures, and test-only dependencies in the source repository and source archives. Do **not** install them with the normal Arch package or run them during ordinary app use. Package builds may run the suite in `check()` when suitable; keep runtime dependencies minimal.

## P1 — First-run setup wizard

- [ ] Detect KDE Plasma Wayland and explain unsupported environments.
- [ ] Check required commands, PipeWire availability, and capture permissions without modifying system settings automatically.
- [ ] Offer a safe Epic Seven window setup and capture test.
- [ ] Guide users through creating the global Pause/Resume shortcut.
- [ ] Record successful onboarding and allow reopening it later.

## P1 — Packaging and release review

- [x] Audit `arch/PKGBUILD` dependencies and installed file list. (Public URL/checksum pending.)
- [x] Confirm config, state, and diagnostic paths follow XDG conventions and survive package upgrades.
- [ ] Check clean-system installation, desktop launcher, icon, uninstall, and reinstall behavior.
- [ ] Review license and redistribution permissions for game screenshots, templates, and GUI icons.
- [x] Add a changelog and clear supported-platform documentation.
- [ ] Publish a tagged GitHub v1.0 source release after testing; prepare AUR submission when registration is available.

## P2 — About and version information

- [ ] Show application version, repository, license, KDE/Wayland compatibility, and active capture backend.
- [ ] Document updates through the user's package manager; avoid a competing self-updater.

## P2 — Safer error recovery

- [ ] Retry transient frame/capture failures within a small bound.
- [ ] Pause on lost foreground focus, changed window geometry, or repeated capture failure.
- [ ] Always pause for unclear purchase state; never blindly retry a buy or refresh.
- [ ] Record retries and intervention reasons in the activity log/session history.

## P2 — Expanded performance analytics

- [ ] Track average, minimum, and maximum refresh time.
- [ ] Track average purchase duration, animation waiting, retry count, and manual intervention count.
- [ ] Include these metrics in CSV/JSON session exports.
- [ ] Verify metrics add negligible overhead.

## Release gate

- [ ] Offline regression suite passes.
- [ ] Manual smoke test: window setup, continuous capture, two different offers, duplicate-handling fixture, sold-row verification, limits, final shop, Pause/Resume, End session, and exports.
- [ ] Clean Arch package installs and launches without the development directory.
- [ ] Documentation and asset licensing review complete.

## Out of scope for v1.0

- Unverified changes to working detection thresholds, click timings, or purchase behavior.
- Fully automatic recovery from uncertain purchase dialogs.
- App-managed system/package updates.
