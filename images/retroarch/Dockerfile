# Wolf app image: RetroArch "PlayStation" (XMB menu, PS2 LRPS2 + PSP PPSSPP cores),
# sharing the host flatpak RetroArch setup mounted by Wolf (config, playlists, thumbnails);
# the cores themselves are bundled in the image.
# Build context: images/ (docker compose --profile images build, or Wolfy)
FROM ghcr.io/games-on-whales/retroarch:edge

# no bar (RetroArch is fullscreen), hide the idle mouse cursor
RUN sed -i '/^bar swaybar_command waybar/d' /cfg/sway/config \
    && sed -i '/^# Need to autostart/i seat * hide_cursor 3000' /cfg/sway/config

# libretro cores (latest libretro buildbot builds) + their .info files, in /opt/wolfy.
# Rebuilding the image (Wolfy > Émulateurs > Reconstruire) updates them.
ARG CORES="pcsx2 ppsspp"
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
    rm -f core.zip info.zip; chmod -R a+rX /opt/wolfy; ls -l /opt/wolfy/cores /opt/wolfy/info

# session playlists pointing to the image's cores, changes written back to the shared ones
COPY retroarch/playlist-sync.py /opt/gow/playlist-sync.py
RUN chmod +x /opt/gow/playlist-sync.py

# gamepad combos (RetroArch menu / quit the session), set from Wolfy
COPY common/home-combo.py /opt/gow/home-combo.py
RUN chmod +x /opt/gow/home-combo.py

COPY retroarch/startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/startup-app.sh
