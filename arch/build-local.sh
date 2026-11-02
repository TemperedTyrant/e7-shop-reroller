#!/usr/bin/env bash
set -euo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname -- "$package_dir")"
pkgname='e7-shop-reroller'
pkgver='1.0.0'
archive="${package_dir}/${pkgname}-${pkgver}.tar.gz"

if ! command -v kdotool >/dev/null 2>&1; then
  printf '%s\n' 'Missing kdotool (AUR). Install it first, for example: paru -S kdotool' >&2
  exit 1
fi
if ! command -v makepkg >/dev/null 2>&1; then
  printf '%s\n' 'Missing makepkg. Install base-devel first: sudo pacman -S --needed base-devel' >&2
  exit 1
fi

# Source only the Linux runtime, templates, and packaging files. The original
# Windows binaries, ADB tools and notebook are not needed in an Arch package.
tar -czf "$archive" -C "$project_dir" \
  LICENSE README-LINUX.md \
  secret_shop_gui.py linux_shop.py run_policy.py wayland_cycle.py window_setup.py \
  continuous_capture.py pipewire_helper.py session_history.py stop_shop.py \
  tests/test_run_policy.py tests/test_window_geometry.py tests/test_recognition.py \
  assets/cov.png assets/mys.png assets/fb.png \
  assets/gui/covenant.png assets/gui/mystic.png \
  assets/gui/friendship.png assets/gui/skystone.png \
  arch/PKGBUILD arch/build-local.sh arch/e7-shop-reroller.desktop \
  arch/bin/e7-shop-reroller arch/bin/e7-shop-reroller-toggle \
  arch/bin/e7-secret-shop arch/bin/e7-secret-shop-toggle

printf 'Built local source archive: %s\n' "$archive"
cd "$package_dir"
makepkg -si
