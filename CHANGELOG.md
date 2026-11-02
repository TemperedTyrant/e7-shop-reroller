# Changelog

## 1.1.0 — Unreleased

- Human-readable elapsed time, ETA, and performance timing breakdowns.
- Expected drop counts use a provisional at-least-one-per-shop model, assuming
  each currency appears at most once per shop. The assumption remains unverified.
- Detailed per-shop records for new sessions: detected offers and outcomes,
  purchases, scan duration, and refresh duration/outcome.
- Session-details viewer with purchased-versus-expected totals and per-shop drill-down.
- Detailed CSV/JSON exports for an individual run or all recorded runs, alongside
  the existing summary exports.
- Additive SQLite schema upgrade preserves existing session summaries. Older
  sessions do not gain shop details retroactively; stored expected values are
  not recalculated.
- Offline tests for duration formatting, detailed exports, and history migration.

## 1.0.0

- KDE Wayland Secret Shop automation with supervised purchasing and refresh limits.
- Automatic window activation, positioning, geometry checks and dynamic recognition scaling.
- Optional continuous PipeWire capture with Spectacle fallback.
- Purchase verification by disabled Buy-state and changed availability counter.
- Global Pause/Resume toggle, manual interventions and End session.
- Persistent session statistics, performance metrics, CSV/JSON exports and history management.
- Support for separate offers of the same currency in different shop rows.
- Local Arch PKGBUILD, desktop launcher and XDG user-data storage.
- Offline tests for geometry, limits, statistics, scaling and synthetic image matching.

