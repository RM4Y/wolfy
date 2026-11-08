#!/bin/bash
# Builds the Switch emulator (fork and version: emulator.version) with patches/ (HOME menu and
# Wolfy launcher) and puts the binary in images/switch/patched/bin, copied over the release's by
# Dockerfile, and wolfy-pads (the pads as the emulator sees them, for pad-config.py), linked with
# its own static SDL3. Same flags as the PGO release (compile.sh). The build dir is kept
# (WOLFY_SWITCH_BUILD, default ~/.cache/wolfy-switch-build): rebuilds after a patch change are
# incremental. Version: emulator.version, or the file EMU_VERSION_FILE names (update-emulator.py:
# a new version, written to emulator.version only once it has been built).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=${WOLFY_SWITCH_BUILD:-$HOME/.cache/wolfy-switch-build}
JOBS=${JOBS:-10}
VERSION_FILE=${EMU_VERSION_FILE:-$HERE/emulator.version}
# shellcheck disable=SC1090
. "$VERSION_FILE"

args=()
for k in EMU_NAME EMU_REPO EMU_BINARY EMU_TAG EMU_DATE EMU_COMMIT EMU_LLVM EMU_QT; do
    args+=(--build-arg "$k=${!k}")
done
docker build -t wolfy-switch-builder -f "$HERE/builder.Dockerfile" "${args[@]}" "$HERE"
mkdir -p "$BUILD/release" "$BUILD/cpm" "$HERE/patched/bin"
docker run --rm -e JOBS="$JOBS" -e OWNER="$(id -u):$(id -g)" -v "$HERE:/switch" \
    -v "$BUILD/release:/src/build/release" -v "$BUILD/cpm:/src/.cache/cpm" \
    wolfy-switch-builder bash /switch/compile.sh
