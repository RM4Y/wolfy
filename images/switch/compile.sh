#!/bin/bash
# Compiles the patched Switch emulator, inside wolfy-switch-builder (run by build.sh and by Wolfy's
# update).
#   /switch            images/switch (patches, wolfy-pads.c; patched/bin and emulator.version written)
#   /src/build/release the build dir, kept between builds (incremental after a patch change)
#   /src/.cache/cpm    the bundled dependencies
# OWNER (uid:gid) owns the files written to /switch. On success only: patched/bin/{emulator,
# wolfy-pads,emulator.version}, then images/switch/emulator.version (the version the image uses).
set -euo pipefail
trap 'echo "ÉCHEC (compile.sh ligne $LINENO) : $BASH_COMMAND"' ERR
cd /src
OWNER=${OWNER:-0:0}
JOBS=${JOBS:-10}
# shellcheck disable=SC1091
. /emulator-version
echo "== $EMU_NAME $EMU_TAG ($EMU_COMMIT), clang $LLVM, Qt $(readlink /opt/qt/current)"

echo "== Patches"
for p in /switch/patches/*.patch; do
    if ! git apply "$p"; then
        echo "ÉCHEC : le patch $(basename "$p") ne s'applique plus sur $EMU_NAME $EMU_TAG."
        echo "Rien n'a été modifié : la version installée reste en place. Le patch doit être adapté."
        exit 3
    fi
    echo "   $(basename "$p") : appliqué"
done

# another checkout (new version or fork, or the builder image rebuilt: every source file has a new
# date, so CMake would configure again, and configuring an existing dir fails on the bundled
# OpenSSL): clean build
if [ "$(cat build/release/.emulator-source-id 2>/dev/null)" != "$(cat /emulator-source-id)" ]; then
    echo "== Nouvelles sources : compilation complète (dossier de compilation vidé)"
    find build/release -mindepth 1 -delete
fi
# a file a removed patch changed is back to its old date: without this, ninja keeps the objects
# built from the patched version, and the binary mixes both (crashes at boot on a changed class)
list=build/release/.patched-files
git diff --name-only HEAD >/tmp/patched-files
{ cat "$list" 2>/dev/null || true; cat /tmp/patched-files; } | sort -u | while read -r f; do [ ! -e "$f" ] || touch "$f"; done
cp /tmp/patched-files "$list"

profile=""
if [ -s eglantine.profdata ]; then
    profile="-fprofile-use=$PWD/eglantine.profdata -Wno-backend-plugin -Wno-profile-instr-unprofiled -Wno-profile-instr-out-of-date"
else
    echo "ATTENTION : pas de eglantine.profdata dans cette version, compilation sans PGO"
fi
extra=()
if [ "$EMU_BINARY" = lichii ]; then  # Lichii's version labels
    extra=(-DLICHII_BUILD_TAG="$EMU_TAG" -DLICHII_BUILD_PLATFORM=linux-x86_64-pgo)
fi
if [ ! -f build/release/build.ninja ]; then
    echo "== Configuration"
    cmake -S . -B build/release -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DYUZU_TESTS=OFF -DYUZU_CMD=OFF -DYUZU_ROOM=OFF \
        -DYUZU_ROOM_STANDALONE=OFF -DYUZU_USE_BUNDLED_QT=OFF -DCMAKE_PREFIX_PATH=/opt/qt/current/gcc_64 \
        -DYUZU_USE_BUNDLED_SDL3=ON -DVulkanHeaders_FORCE_BUNDLED=ON -DVulkanUtilityLibraries_FORCE_BUNDLED=ON \
        -DENABLE_UPDATE_CHECKER=OFF -DUSE_DISCORD_PRESENCE=OFF -DUSE_CCACHE=OFF "${extra[@]}" \
        "-DCMAKE_C_COMPILER=clang-$LLVM" "-DCMAKE_CXX_COMPILER=clang++-$LLVM" \
        "-DCMAKE_EXE_LINKER_FLAGS=-B/usr/lib/llvm-$LLVM/bin -fuse-ld=lld -Wl,--as-needed" \
        "-DCMAKE_C_FLAGS=$profile" "-DCMAKE_CXX_FLAGS=$profile"
fi
echo "== Compilation ($JOBS tâches)"
nice -n 19 ninja -C build/release -j "$JOBS" yuzu
cp /emulator-source-id build/release/.emulator-source-id

echo "== Binaires"
tmp=$(mktemp -d)
strip -o "$tmp/emulator" "build/release/bin/$EMU_BINARY"
# the libraries of the release AppImage (linuxdeploy does the same to its binary)
patchelf --set-rpath "\$ORIGIN/../lib" "$tmp/emulator"
sdl=$(sed -n "s/^CPM_PACKAGE_SDL3_SOURCE_DIR:INTERNAL=//p" build/release/CMakeCache.txt)
gcc -O2 -Wno-format-truncation -o "$tmp/wolfy-pads" /switch/wolfy-pads.c -I"$sdl/include" "$sdl/lib/libSDL3.a" -lm -ldl -lpthread
strip "$tmp/wolfy-pads"
cp /emulator-version "$tmp/emulator.version"
out=/switch/patched/bin
mkdir -p "$out"
for f in emulator wolfy-pads emulator.version; do
    cp "$tmp/$f" "$out/.$f.new" && mv -f "$out/.$f.new" "$out/$f"
done
chown "$OWNER" "$out" "$out/emulator" "$out/wolfy-pads" "$out/emulator.version"

# the version the app image is built from (comments of the current file kept)
{ grep '^#' /switch/emulator.version 2>/dev/null || true; cat /emulator-version; } >"$tmp/version"
cat "$tmp/version" >/switch/emulator.version
chown "$OWNER" /switch/emulator.version
ls -la "$out"
echo "== $EMU_NAME $EMU_TAG compilé"
