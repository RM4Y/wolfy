# Wolf app image "Switch" (wolfy-switch:latest): the Switch emulator fork of emulator.version
# (Eglantine, or Lichii) with Wolfy's patches (build.sh, run it first: it builds patched/bin).
# wolfy-launcher.py runs the HOME menu and each game (Switch 1 or 2) in processes of their own.
# Build context: images/ (Wolfy › Émulateurs › Reconstruire, or:
#   docker build -f switch/Dockerfile -t wolfy-switch:latest .)
#   switch/emulator.version: the release (its libraries) and the sources patched/bin was built
#   from; both must match (update-emulator.py, or Wolfy › Émulateurs › Mettre à jour, keeps them together)
FROM ubuntu:25.04 AS extract
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 squashfs-tools \
    && rm -rf /var/lib/apt/lists/*
COPY switch/emulator.version /tmp/emulator.version
COPY switch/patched/bin/emulator.version /tmp/patched.version
RUN for k in EMU_REPO EMU_COMMIT; do \
        [ "$(grep "^$k=" /tmp/emulator.version)" = "$(grep "^$k=" /tmp/patched.version)" ] \
        || { echo "patched/bin n'a pas été compilé pour emulator.version : lance switch/build.sh"; exit 1; }; \
    done
COPY switch/fetch-release.py switch/emu_release.py /tmp/
RUN python3 /tmp/fetch-release.py /tmp/emulator.version /opt/emu
# the patched binary (switch/build.sh) over the release's
COPY switch/patched/bin/emulator /tmp/emulator
RUN . /tmp/emulator.version && test -f "/opt/emu/usr/bin/$EMU_BINARY" \
    && cp /tmp/emulator "/opt/emu/usr/bin/$EMU_BINARY" && chmod -R a+rX /opt/emu

FROM ghcr.io/games-on-whales/base-app:edge

# libraries linuxdeploy leaves to the system (Qt's xcb platform plugin, libusb)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
        libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 libxcb-shape0 libxcb-randr0 \
        libxcb-xfixes0 libxcb-sync1 libxcb-glx0 libegl1 libgl1 libopengl0 libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=extract /opt/emu /opt/emu
# players 1-4 = the pads of the session, set before each emulator process (wolfy-launcher.py)
COPY switch/patched/bin/wolfy-pads /opt/gow/wolfy-pads
COPY switch/pad-config.py /opt/gow/pad-config.py

# HOME menu and games in processes of their own, gamepad combos (HOME, quit)
COPY switch/wolfy-launcher.py /opt/wolfy-launcher.py
COPY common/home-combo.py /opt/gow/home-combo.py
COPY switch/startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/home-combo.py /opt/gow/startup-app.sh /opt/gow/wolfy-pads /opt/gow/pad-config.py

COPY common/20-fix-home-perms.sh /etc/cont-init.d/20-fix-home-perms.sh
RUN chmod +x /etc/cont-init.d/20-fix-home-perms.sh

# no bar, no window borders, and the main window fullscreen (dialogs stay floating)
RUN sed -i '/^bar swaybar_command waybar/d' /cfg/sway/config \
    && sed -i '/^# Need to autostart/i default_border none\ndefault_floating_border none' /cfg/sway/config \
    && sed -i '/^# Need to autostart/i for_window [class="(?i)(eglantine|lichii|eden)" window_type="normal"] fullscreen enable' /cfg/sway/config

ARG IMAGE_SOURCE
LABEL org.opencontainers.image.source=$IMAGE_SOURCE
