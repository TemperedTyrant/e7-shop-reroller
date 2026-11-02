# E7 Shop Reroller — KDE Plasma Wayland

An unofficial Secret Shop reroll assistant for the PC edition of E7. It detects
Covenant Bookmarks, Mystic Medals, and Friendship Points, automates selected
purchases and refreshes, and records session statistics.

**Publisher notice:** This project is not endorsed by Smilegate. The game's
published terms restrict unauthorized automation tools. Use may put your game
account at risk; review those terms before deciding whether to use the app.

**Tested:** Arch Linux, KDE Plasma Wayland, game via Steam/Proton at 1280×720
and a resized game at approximately 1008×567 on a 4:3 desktop configuration.
800×480 is unsupported; 1080p and Steam Deck are not yet independently verified.
Supervise all live runs.

## Local Arch installation

For a local Arch build, clone the repository and run:

```sh
sudo pacman -S --needed base-devel
paru -S kdotool
git clone https://github.com/TemperedTyrant/e7-shop-reroller.git
cd e7-shop-reroller
bash arch/build-local.sh
```

The build script archives only the Linux runtime and essential files, then
runs `makepkg -si`. It includes offline regression tests in the **build source**
and runs them before installing; test files are not installed with the app.
Other dependencies are managed by pacman. `ydotoold` must
be configured separately; installation does not enable input services.

Launch **E7 Shop Reroller** from the application menu, or run
`e7-shop-reroller`. Configure your KDE shortcut to use
`/usr/bin/e7-shop-reroller-toggle`.

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

### Arch release builds (GitHub Actions)

Every new `vX.Y.Z` tag triggers an Arch Linux package build using the
verified source archive and `arch/PKGBUILD.aur.template` from `main`.
The workflow also supports manual runs under **Actions → Build Arch release
package → Run workflow**, including for the existing `v1.0.0` release.

After the package builds and offline tests pass, the workflow uploads an
**unsigned** `.pkg.tar.zst` plus its checksum and `.SRCINFO` as an Actions
artifact (retained for 30 days). A separate job verifies the package checksum
and attaches the package and checksum to the matching **published GitHub
release**. It never replaces existing release files automatically; reruns
keep existing assets. The workflow also runs when a GitHub release is published.
It does not publish an AUR package. Release downloads are not a pacman
repository and do not provide automatic updates.

The build uses an official Arch Linux container. CI skips the check that all
AUR runtime dependencies are installed, because `kdotool` is not in Arch's
official repositories; the generated package retains its declared `kdotool`
dependency. The offline tests still run with system OpenCV. A real KDE
Wayland session is required for live end-to-end verification.

For subsequent releases, update the AUR template's version and verified
source archive checksum on `main` before starting the tagged build.

### KDE global shortcut

Bind a **Command or Script** shortcut in **KDE System Settings → Keyboard →
Shortcuts** to `/usr/bin/e7-shop-reroller-toggle`, optionally using
`Ctrl+Alt+Shift+F12` if available. The shortcut toggles
Pause/Resume for an *active* session; it does not start a session.

KDE supports application-provided shortcuts, but this version does not claim
or overwrite any key combinations automatically.

## Data, history and exports

User data is stored in XDG directories:

| Data | Default path |
| --- | --- |
| Settings | `~/.config/e7-shop-reroller/settings.json` |
| Session history | `~/.local/state/e7-shop-reroller/history.sqlite3` |
| Diagnostic folders | `~/.local/state/e7-shop-reroller/run-history/` |

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

This is a standalone Linux application **based on**
[Solunium/Epic-Seven-E7-Secret-Shop-Refresh](https://github.com/Solunium/Epic-Seven-E7-Secret-Shop-Refresh),
not a GitHub fork of that repository. It retains the original project's recognition
image templates and overall shop-rerolling concept; the KDE Wayland integration,
window management, GUI, run controls, session statistics and packaging were
substantially reworked for this project. Credit to the original contributors
is retained, and their GPL obligations remain applicable to any reused code.

The **application code** is distributed under the GNU General Public License
version 3 (`GPL-3.0-only`); see [LICENSE](LICENSE). You may use, inspect, modify
and redistribute covered code under its terms, including making modified
source available when distributing derivatives. The license does not grant
rights to third-party game artwork or endorse the use of automation.

`arch/PKGBUILD` is the **local development build** and intentionally uses a
local archive and `SKIP` checksum. For a tagged source archive, use `arch/PKGBUILD.aur.template` from the
current `main` branch after its checksum is verified against the final tag.
Copy it to `PKGBUILD` when preparing an AUR submission and generate `.SRCINFO`
with `makepkg --printsrcinfo > .SRCINFO`.
