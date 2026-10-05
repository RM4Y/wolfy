#!/bin/bash
# Builds the patched Eden (Dockerfile + patches/) and lays it out in images/eden/patched/,
# copied over the AppImage's files (/opt/eden/shared) by images/eden/Dockerfile:
#   bin/eden   patched binary
#   lib/       libraries it needs that the AppImage doesn't ship in the same version
#              (Boost, fmt, and glibc: built on today's Arch, newer than the AppImage's)
# The build dir is kept (WOLFY_EDEN_BUILD, default ~/.cache/wolfy-eden-build): rebuilds
# after a patch change are incremental.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/../patched
BUILD=${WOLFY_EDEN_BUILD:-$HOME/.cache/wolfy-eden-build}
JOBS=${JOBS:-10}

DOCKER_BUILDKIT=1 docker build --target deps -t wolfy-eden-builder "$HERE"
mkdir -p "$BUILD"
docker run --rm -v "$BUILD:/eden/build" wolfy-eden-builder sh -c "cd /eden \
    && { [ -f build/CMakeCache.txt ] || cmake -S . -B build \$EDEN_CMAKE_ARGS; } \
    && nice -n 19 ninja -C build -j $JOBS yuzu"

rm -rf "$OUT" && mkdir -p "$OUT/bin" "$OUT/lib"
docker run --rm -v "$BUILD:/eden/build:ro" -v "$OUT:/out" wolfy-eden-builder sh -c '
    strip -o /out/bin/eden /eden/build/bin/eden
    cd /usr/lib
    cp -L libboost_filesystem.so.1.92.0 libboost_context.so.1.92.0 libfmt.so.12 \
          ld-linux-x86-64.so.2 libc.so.6 libm.so.6 libdl.so.2 libpthread.so.0 librt.so.1 \
          libnss_dns.so.2 libnss_files.so.2 /out/lib/
    chown -R '"$(id -u):$(id -g)"' /out'
ls -la "$OUT/bin" "$OUT/lib"
