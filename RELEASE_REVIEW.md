# E7 Shop Reroller — pre-release review

Status: **private candidate; not cleared for a public v1.0 release**.

## 1. Artwork and game policies

The application bundles these recognizable game-derived files:

| Files | Purpose | Provenance / permission status |
| --- | --- | --- |
| `assets/cov.png`, `assets/mys.png`, `assets/fb.png` | Image matching | Derived from the upstream project; there is no independently verified license from the game's artwork owner. |
| `assets/gui/covenant.png`, `assets/gui/mystic.png`, `assets/gui/friendship.png`, `assets/gui/skystone.png` | UI icons | Transparent game-derived images provided during development; no independently verified redistribution permission. |

The source code is based on Solunium's GPL-3.0 project. Its GPL license does
not, by itself, license the game's underlying artwork. The publisher's terms
also restrict unauthorized automation software. A noncommercial fan-content
policy is not necessarily authorization to distribute an automation program.

Before public release, decide whether to (a) obtain permission to redistribute
the seven assets or (b) distribute source without game-derived images and
provide an authorized, user-side acquisition/calibration flow. Do not label
these assets as GPL-licensed without confirmation.

Relevant policies:

- https://common.game.onstove.com/terms/index?gameType=MOBILE&langCode=en&termsType=1
- https://common.game.onstove.com/terms/index?gameType=MOBILE&langCode=en&termsType=3

## 2. Arch dependency audit

The runtime currently requires Python, Tk, NumPy, OpenCV, Spectacle, KWin
(`kdotool`), `ydotool`, and the PipeWire/GStreamer/portal stack. Continuous
capture is optional in the UI, but the package includes the required backend
so users can enable it without reinstalling.

Arch's `python-opencv` imports the main OpenCV package, VTK and OpenMPI; the
resulting installation is significantly larger than the application itself.
The headless PyPI wheel is smaller but would require maintaining a separate
Python environment or a custom native Arch package. Neither change is yet
validated for Arch packaging. Retain the tested official dependency for v1.0.

## 3. Public release packaging

- [x] Project repository: https://github.com/TemperedTyrant/e7-shop-reroller
- [x] Linux runtime, test suite, local PKGBUILD and build script committed.
- [x] All 17 tests passed on the maintainer's Arch installation.
- [x] Private build uses pacman-managed dependencies and does not install tests.
- [ ] Resolve or explicitly decide on artwork redistribution and policy risk.
- [ ] Select a final commit and create an immutable release tag `v1.0.0`.
- [ ] Change AUR `source` to the tagged GitHub tarball and calculate its actual SHA-256.
- [ ] Adapt `package()`/`check()` paths to GitHub's archive root directory.
- [ ] Generate `.SRCINFO` from the final AUR PKGBUILD.
- [ ] Perform clean-install validation on the final release-source package.
- [ ] Publish a GitHub release, then submit to AUR when appropriate.

**Important:** The development PKGBUILD uses a local tarball and `SKIP` for its
checksum. It is not the final AUR PKGBUILD. A tagged download and verified hash
must replace these fields before publishing.
