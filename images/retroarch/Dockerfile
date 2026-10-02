# Wolf app image: RetroArch "PlayStation" (XMB menu, PS1 Beetle PSX HW + PS2 LRPS2 + PSP PPSSPP cores),
# sharing the host flatpak RetroArch setup mounted by Wolf (config, playlists, thumbnails);
# the cores themselves are bundled in the image.
# PS3 (RPCS3) and PS Vita (Vita3K) are standalone emulators started from the XMB by a small
# "launcher" libretro core (launcher-core.c, ps-launch); their games get their own playlists.
# Build context: images/ (docker compose --profile images build, or Wolfy)

# ---------------------------------------------------------------- launcher cores
FROM ghcr.io/games-on-whales/base-app:edge AS build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY retroarch/launcher-core.c /src/launcher-core.c
RUN curl -fsSL -o /src/libretro.h \
      https://raw.githubusercontent.com/libretro/libretro-common/master/include/libretro.h \
    && mkdir -p /out \
    && cc -O2 -shared -fPIC -o /out/wolfy_rpcs3_libretro.so /src/launcher-core.c \
         -DEMU='"rpcs3"' -DLIB_NAME='"RPCS3"' -DEXTS='"bin|elf|self"' \
    && cc -O2 -shared -fPIC -o /out/wolfy_vita3k_libretro.so /src/launcher-core.c \
         -DEMU='"vita3k"' -DLIB_NAME='"Vita3K"' -DEXTS='"bin"'

# ---------------------------------------------------------------- glibc for Vita3K
# Vita3K's Linux builds need a newer glibc than this image's Ubuntu: it gets its own
# (loader + libraries), used by the Vita3K binary only (patchelf below)
# (+ libwayland, newer than this image's too)
FROM ubuntu:26.04 AS glibc
RUN apt-get update && apt-get install -y --no-install-recommends libwayland-client0 libwayland-cursor0 \
      libwayland-egl1 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /out && cp -L /lib64/ld-linux-x86-64.so.2 /out/ \
    && for l in libc.so.6 libm.so.6 libmvec.so.1 libpthread.so.0 libdl.so.2 librt.so.1 libresolv.so.2 \
                libanl.so.1 libutil.so.1 libwayland-client.so.0 libwayland-cursor.so.0 libwayland-egl.so.1; do \
      cp -L /lib/x86_64-linux-gnu/$l /out/; done \
    && /out/ld-linux-x86-64.so.2 --version | head -1

# ---------------------------------------------------------------- app
FROM ghcr.io/games-on-whales/retroarch:edge
ARG DEBIAN_FRONTEND=noninteractive
# xvfb: firmware / pkg installs run by Wolfy (Vita3K needs a display even for those)
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth patchelf \
    && rm -rf /var/lib/apt/lists/*

# no bar (RetroArch is fullscreen), hide the idle mouse cursor
RUN sed -i '/^bar swaybar_command waybar/d' /cfg/sway/config \
    && sed -i '/^# Need to autostart/i seat * hide_cursor 3000' /cfg/sway/config

# libretro cores (latest libretro buildbot builds) + their .info files, in /opt/wolfy.
# Rebuilding the image (Wolfy > Émulateurs > Reconstruire) updates them.
ARG CORES="mednafen_psx_hw pcsx2 ppsspp"
ARG BUILDBOT=https://buildbot.libretro.com/nightly/linux/x86_64/latest
RUN set -e; mkdir -p /opt/wolfy/cores /opt/wolfy/info; cd /tmp; \
    for c in $CORES; do \
      curl -fsSL -o core.zip "$BUILDBOT/${c}_libretro.so.zip"; \
      date=$(curl -fsSI "$BUILDBOT/${c}_libretro.so.zip" | sed -n 's/^last-modified: //Ip' | tr -d '\r'); \
      python3 -c "import zipfile; zipfile.ZipFile('core.zip').extractall('/opt/wolfy/cores')"; \
      echo "${c}_libretro.so  $date" >> /opt/wolfy/cores/VERSIONS; \
    done; \
    curl -fsSL -o info.zip https://buildbot.libretro.com/assets/frontend/info.zip; \
    python3 -c "import zipfile, sys; z = zipfile.ZipFile('info.zip'); [z.extract(n, '/opt/wolfy/info') for n in z.namelist() if n.split('_libretro')[0] in sys.argv[1:]]" $CORES; \
    rm -f core.zip info.zip

# RPCS3 (latest Linux build) and Vita3K (latest build), AppImages extracted in /opt.
# Rebuilding the image updates them too.
RUN set -e; cd /tmp; \
    url=$(curl -fsSL https://api.github.com/repos/RPCS3/rpcs3-binaries-linux/releases/latest \
          | python3 -c "import json, sys; print(next(a['browser_download_url'] for a in json.load(sys.stdin)['assets'] if a['name'].endswith('.AppImage')))"); \
    curl -fsSL -o rpcs3.AppImage "$url"; chmod +x rpcs3.AppImage; ./rpcs3.AppImage --appimage-extract >/dev/null; \
    mv "$(readlink -f squashfs-root)" /opt/rpcs3; rm -f squashfs-root rpcs3.AppImage; \
    echo "rpcs3  $(basename "$url")" >> /opt/wolfy/cores/VERSIONS; \
    curl -fsSL -o vita3k.AppImage https://github.com/Vita3K/Vita3K/releases/download/continuous/Vita3K-x86_64.AppImage; \
    chmod +x vita3k.AppImage; ./vita3k.AppImage --appimage-extract >/dev/null; \
    mv "$(readlink -f squashfs-root)" /opt/vita3k; rm -f squashfs-root vita3k.AppImage; \
    echo "vita3k  $(curl -fsSL https://api.github.com/repos/Vita3K/Vita3K/releases/tags/continuous | python3 -c "import json, sys; print(json.load(sys.stdin)['published_at'])")" >> /opt/wolfy/cores/VERSIONS
COPY --from=glibc /out /opt/vita3k/glibc
# Vita3K: its own glibc; "portable" mode = every file (config.yml, ux0, firmware, cache) in the
# folder Wolf mounts at ~/.local/share/Vita3K
RUN patchelf --set-interpreter /opt/vita3k/glibc/ld-linux-x86-64.so.2 \
      --set-rpath /opt/vita3k/glibc:/opt/vita3k/usr/lib --force-rpath /opt/vita3k/usr/bin/Vita3K \
    && ln -s /home/retro/.local/share/Vita3K /opt/vita3k/usr/bin/portable \
    && test -x /opt/rpcs3/usr/bin/rpcs3 && test -x /opt/vita3k/usr/bin/Vita3K \
    && ! ldd /opt/rpcs3/usr/bin/rpcs3 | grep 'not found' \
    && ! /opt/vita3k/glibc/ld-linux-x86-64.so.2 --list /opt/vita3k/usr/bin/Vita3K | grep 'not found'

# launcher cores (PS3, PS Vita) + their .info files
COPY --from=build /out/ /opt/wolfy/cores/
COPY retroarch/launcher-info/ /opt/wolfy/info/
COPY retroarch/ps-launch retroarch/rpcs3-pads.py retroarch/ps-playlists.py retroarch/ps-session-setup.py /opt/wolfy/bin/
RUN chmod +x /opt/wolfy/bin/* && chmod -R a+rX /opt/wolfy /opt/rpcs3 /opt/vita3k \
    && ls -l /opt/wolfy/cores /opt/wolfy/info && cat /opt/wolfy/cores/VERSIONS

# session playlists pointing to the image's cores, changes written back to the shared ones
COPY retroarch/playlist-sync.py /opt/gow/playlist-sync.py
RUN chmod +x /opt/gow/playlist-sync.py

# gamepad combos (RetroArch menu / quit the session), set from Wolfy
COPY common/home-combo.py /opt/gow/home-combo.py
RUN chmod +x /opt/gow/home-combo.py

COPY retroarch/startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/startup-app.sh
