# E7 Shop Reroller — KDE Plasma Wayland

An unofficial Secret Shop reroll assistant for the PC edition of E7. It detects
Covenant Bookmarks, Mystic Medals, and Friendship Points, automates selected
purchases and refreshes, and records session statistics.

**Tested:** Arch Linux, KDE Plasma Wayland, game via Steam/Proton at 1280×720
and a resized game at approximately 1008×567 on a 4:3 desktop configuration.
800×480 is unsupported; 1080p and Steam Deck are not yet independently verified. The project is not
affiliated with the game's publisher. Check its automation policies before use
and supervise all live runs.

## Local Arch installation

This is a **local-source PKGBUILD**, not yet an AUR release. Run from the
extracted project folder:

```sh
sudo pacman -S --needed base-devel
paru -S kdotool
bash arch/build-local.sh
```

The build script archives only the Linux runtime and essential templates, then
runs `makepkg -si`. It includes offline regression tests in the **build source**
and runs them before installing; test files are not installed with the app.
Other dependencies are managed by pacman. `ydotoold` must
be configured separately; installation does not enable input services.

Launch **E7 Shop Reroller** from the application menu, or run
`e7-shop-reroller`. The renamed package replaces/conflicts with the previous
`e7-secret-shop-linux` package. Compatibility commands `e7-secret-shop` and
`e7-secret-shop-toggle` remain available so existing KDE shortcuts still work.

## Usage

1. Open the Secret Shop at the top of the list.
2. Choose items and **one** limit: paid refreshes or Skystones spent.
3. Use **Window setup & calibration… → Test Window Setup** to verify geometry
   without buying or refreshing.
4. Use **Test scan (read-only)** to check detection without mouse input.
5. Select **Start run**, read the spending confirmation, and supervise the game.

The app activates, sizes and positions the game window before running. It
scans upper and lower items, buys selected rows, then refreshes for 3 Skystones.
The final refreshed shop **is scanned**: 10 paid refreshes review 11 shops.

Purchase verification requires the row availability area to change and its
Buy label to become disabled (the expected `1/1` → `0/1` transition). This is
not digit OCR or independent inventory/Gold verification. Inconclusive actions
pause for manual inspection. Use **Pause** at a safe checkpoint, **Resume**
after resolving the problem, or **End session** to terminate.

### Recognition & Input

Hover over a **?** next to a setting for help.

| Setting | Meaning |
| --- | --- |
| Match threshold (`0.70`) | Minimum image-match confidence. Lower values risk false positives; higher values can miss items. |
| Input delay (`0.35 s`) | Wait after each click; supported `0.20–10 s`. The minimum `0.20 s` has been tested. |
| Dialog-change score (`8.0`) | Required visual difference to recognize a Buy/Refresh dialog transition. |
| Continuous capture | Checked uses a PipeWire window stream (fast); unchecked takes individual Spectacle screenshots (slower). |

When KDE asks what to share, select the **game window**, not the monitor.
The stream is checked against a Spectacle image before use.

### Display compatibility

Window setup targets 1280×720 content when it fits, otherwise uses a smaller
16:9 rectangle on the monitor currently containing Epic Seven. Recognition
templates scale with the measured content width. The game must fit at least
960×540 plus window decorations. Small KWin positioning adjustments are
accepted only after verified screenshot geometry; unsupported layouts stop
before sending clicks. Fractional KDE scaling and Steam Deck remain unverified.

### Offline tests (source checkout)

On Arch, install the PKGBUILD's Python runtime dependencies, then run:

```sh
python -B -m unittest discover -s tests -v
```

Tests do not launch the game or send mouse input. They cover limit arithmetic,
expected values, dynamic scaling, monitor selection, and synthetic template
matching including duplicate currency offers and Buy label states. Recognition
tests require OpenCV; if missing, they report **skipped**. A GitHub Actions job
installs these dependencies before running the complete suite. Manual live
testing is still required for KWin, PipeWire, clicking, and actual game animations.

### KDE global shortcut

Bind a **Command or Script** shortcut in **KDE System Settings → Keyboard →
Shortcuts** to `/usr/bin/e7-shop-reroller-toggle`, optionally using
`Ctrl+Alt+Shift+F12` if available. Existing bindings to
`/usr/bin/e7-secret-shop-toggle` continue working. The shortcut toggles
Pause/Resume for an *active* session; it does not start a session.

KDE supports application-provided shortcuts, but this version does not claim
or overwrite any key combinations automatically.

## Data, history and exports

Existing XDG locations are deliberately retained for backward compatibility:

| Data | Default path |
| --- | --- |
| Settings | `~/.config/e7-secret-shop/settings.json` |
| Session history | `~/.local/state/e7-secret-shop/history.sqlite3` |
| Diagnostic folders | `~/.local/state/e7-secret-shop/run-history/` |

The app honors XDG config/state overrides. Package upgrades preserve data.
**Session history…** shows saved runs. Export CSV/JSON for further analysis.
**Clear history & data…** lets you separately remove session records, diagnostic
folders, or reset preferences. Deletion needs confirmation and cannot run during
an active session.

Performance statistics show elapsed time, refreshes/minute, frame count and
capture/recognition/cursor/scroll/waiting totals. Expected item counts are
calculated as six slots per shop times in-game Level 13 rates: Covenant
0.6602509%, Mystic 0.1700646%, Friendship 19.1772874%. These are statistical
expectations, not guarantees.

## Source and licensing

The runtime uses Python, Tkinter, OpenCV, PipeWire/GStreamer, Spectacle, KWin
and ydotool. The original recognition templates in `assets/` remain unchanged;
transparent `assets/gui/` icons are display-only.

Forked from [Solunium/Epic-Seven-E7-Secret-Shop-Refresh](https://github.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh).
See `LICENSE` for source licensing. Game artwork belongs to its owners; review
redistribution rights before publishing to AUR or other catalogs.

**Not yet publication-ready:** `arch/PKGBUILD` still uses the original upstream
URL and a local source archive with a skipped checksum. Set the new project's
actual GitHub release URL, verify a release archive's SHA-256 hash, and update
`.SRCINFO` before submitting to AUR. The GPL license applies to the code; it
does not independently authorize redistribution of copyrighted game images.
