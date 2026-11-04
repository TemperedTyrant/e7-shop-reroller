# Maintainer Guide — E7 Shop Reroller

This document is for developers and release maintainers. End-user installation,
configuration, and usage instructions are in [README.md](README.md).

## Offline tests (source checkout)

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

## Arch release builds (GitHub Actions)

**To publish a new version**, first add its release notes to `CHANGELOG.md`
under an unreleased heading such as `## 1.2.0 — Unreleased` and merge them
into `main`. Then run **Actions → Prepare and publish version → Run workflow**
from `main` and enter the version **without** `v` (for example `1.2.0`).

The workflow updates the local and AUR package versions, commits the tagged
source, computes the GitHub archive SHA256, and pins the verified checksum in
a follow-up `main` commit. A second job runs the offline tests and builds the
Arch package. **Only after the package passes verification** does it create
and publish the GitHub release with the package and checksum attached.

Release tags cannot safely contain their own archive SHA256 because that
would change the archive hash. For that reason, use the *post-tag* pinned
`arch/PKGBUILD.aur.template` from `main` when submitting to AUR. The tag
itself contains the placeholder that was used before the checksum existed.

The separate **Actions → Build Arch release package → Run workflow** remains
available to rebuild an existing published release (for example `v1.0.0`).
It also runs for independently published releases, but pushes of tags by
themselves no longer trigger it. Rebuilds refuse to replace existing assets.
GitHub Actions uses an **unsigned** `.pkg.tar.zst` and `package.sha256`;
the build artifact also includes `.SRCINFO` and is retained for 30 days.

The automated release requires workflow permission to create commits and tags
on `main`. Branch rules that restrict GitHub Actions from pushing will
prevent automated release preparation; do not bypass those protections
silently. It does not submit to AUR. GitHub release packages are not a
pacman repository and do not provide automatic updates.

The build uses an official Arch Linux container. CI skips the check that all
AUR runtime dependencies are installed, because `kdotool` is not in Arch's
official repositories; the generated package retains its declared `kdotool`
dependency. The offline tests still run with system OpenCV. A real KDE
Wayland session is required for live end-to-end verification.

## Packaging files and AUR preparation

`arch/PKGBUILD` is the **local development build** and intentionally uses a
local archive and `SKIP` checksum. For a tagged source archive, use
`arch/PKGBUILD.aur.template` from the current `main` branch after its checksum is verified against the final tag.
Copy it to `PKGBUILD` when preparing an AUR submission and generate `.SRCINFO`
with `makepkg --printsrcinfo > .SRCINFO`.
