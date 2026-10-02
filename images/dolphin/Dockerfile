# Wolf app image: Dolphin "Wii / GameCube", booting the Wii System Menu. Dolphin is the
# Better Wii Menu DE fork (same build as the PC's flatpak): the disc images appear as Wii
# Menu channels (dolphin_forwarders.ini in the shared NAND), so games are picked and
# switched with the Wii Remote only.
# Shares the host flatpak Dolphin setup mounted by Wolf (config copied per session, NAND,
# saves and memory cards shared). Pads: the Wolf pads drive emulated Wii Remotes / GameCube
# pads (SDL mappings written at session start); real Wii Remotes go through the host's
# Bluetooth (the app runs in the host network namespace, see backend/wolfy/emulators.py).
# Build context: images/ (docker compose --profile images build, or Wolfy)

# ---------------------------------------------------------------- build (same Ubuntu as the app)
FROM ghcr.io/games-on-whales/base-app:edge AS build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates build-essential cmake ninja-build pkg-config gettext \
      qt6-base-dev qt6-base-private-dev qt6-svg-dev \
      libevdev-dev libudev-dev libsystemd-dev libx11-dev libxi-dev libxrandr-dev libxext-dev \
      libgl-dev libegl-dev libvulkan-dev libbluetooth-dev libpulse-dev libusb-1.0-0-dev \
      libhidapi-dev libcurl4-openssl-dev libzstd-dev liblzma-dev zlib1g-dev \
      libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Better Wii Menu DE, same commit as the PC's flatpak (Dolphin > About)
ARG REPO=https://github.com/Gavin-S-Dev/Better-Wii-Menu-DE
ARG REF=0e57690c0b0829a2b8870d48e274ead39932e365
RUN git clone --filter=blob:none "$REPO" /src && cd /src && git checkout "$REF" \
    && git submodule update --init --recursive --jobs 8
# the session runs Dolphin in batch mode (quits when emulation stops, see dolphin-run.sh), but
# a Wii Menu game channel launches its disc by stopping emulation and booting it again: don't
# quit while such a boot is pending (the build fails here if the line changes upstream)
RUN f=/src/Source/Core/DolphinQt/MainWindow.cpp \
    && grep -q '  if (m_exit_requested || Settings::Instance().IsBatchModeEnabled())$' "$f" \
    && sed -i 's/^  if (m_exit_requested || Settings::Instance().IsBatchModeEnabled())$/  if (m_exit_requested || (Settings::Instance().IsBatchModeEnabled() \&\& !WiiForwarder::HasPendingForwarderBoot()))/' "$f" \
    && grep -n 'HasPendingForwarderBoot()))' "$f"
# same options as the fork's flatpak manifest (Flatpak/org.DolphinEmu.dolphin-emu.yml)
RUN cmake -S /src -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/dolphin \
      -DENABLE_ALSA=OFF -DENABLE_SDL=ON -DENABLE_EVDEV=ON -DENABLE_TESTS=OFF \
      -DENABLE_AUTOUPDATE=OFF -DENABLE_ANALYTICS=OFF -DUSE_DISCORD_PRESENCE=OFF \
      -DDISTRIBUTOR=wolfy \
    && ninja -C /build && ninja -C /build install \
    && git -C /src describe --always --tags > /opt/dolphin/VERSION
# sdl-pads: the gamepads SDL sees, named exactly as Dolphin names them (same static SDL);
# used by Wolfy to list the PC's gamepads and by the sessions (host-pads.py)
COPY dolphin/sdl-pads.c /tmp/sdl-pads.c
RUN cc -O2 -o /opt/dolphin/bin/sdl-pads /tmp/sdl-pads.c -I/src/Externals/SDL/SDL/include \
      /build/Externals/SDL/SDL/libSDL3.a -lm -ldl -lpthread -lrt

# ---------------------------------------------------------------- app
FROM ghcr.io/games-on-whales/base-app:edge
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libqt6widgets6 libqt6gui6 libqt6svg6 libqt6dbus6 qt6-qpa-plugins libxcb-cursor0 \
      libevdev2 libudev1 libxi6 libxrandr2 libegl1 libgl1 libvulkan1 libbluetooth3 libpulse0 \
      libusb-1.0-0 libhidapi-hidraw0 libcurl4t64 libzstd1 liblzma5 \
      libavcodec61 libavformat61 libavutil59 libswscale8 libswresample5 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/dolphin /opt/dolphin
# every library resolved (a missing one fails the build here, not in a session)
RUN ! ldd /opt/dolphin/bin/dolphin-emu | grep 'not found' && echo "Dolphin $(cat /opt/dolphin/VERSION)"

# no bar (Dolphin is fullscreen), hide the idle mouse cursor
RUN sed -i '/^bar swaybar_command waybar/d' /cfg/sway/config \
    && sed -i '/^# Need to autostart/i seat * hide_cursor 3000' /cfg/sway/config

# gamepad combos (Wii HOME button / quit the session), set from Wolfy
COPY common/home-combo.py /opt/gow/home-combo.py
COPY dolphin/dolphin-setup.py /opt/gow/dolphin-setup.py
COPY dolphin/dolphin-run.sh /opt/gow/dolphin-run.sh
COPY dolphin/host-pads.py /opt/gow/host-pads.py
COPY dolphin/40-host-pads.sh /etc/cont-init.d/40-host-pads.sh
COPY dolphin/startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/home-combo.py /opt/gow/dolphin-setup.py /opt/gow/dolphin-run.sh /opt/gow/startup-app.sh \
      /opt/gow/host-pads.py /etc/cont-init.d/40-host-pads.sh
