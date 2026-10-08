# Wolf app image: Eden (Switch emulator) booting the Switch HOME menu (qlaunch).
# Build context: images/ (docker compose --profile images build, or Wolfy)
FROM ghcr.io/games-on-whales/base-app:edge

# AppImages can't mount (no FUSE in containers): extracted on the host beforehand
# (./eden.AppImage --appimage-extract && mv squashfs-root eden-app)
COPY eden/eden-app /opt/eden
# patched Eden binary + the newer libraries it needs (eden/build/build.sh)
COPY eden/patched/ /opt/eden/shared/
RUN chmod -R a+rX /opt/eden

COPY eden/20-fix-home-perms.sh /etc/cont-init.d/20-fix-home-perms.sh
RUN chmod +x /etc/cont-init.d/20-fix-home-perms.sh

RUN apt-get update && apt-get install -y --no-install-recommends xdotool \
    && rm -rf /var/lib/apt/lists/*
COPY eden/eden-run.sh /opt/gow/eden-run.sh
RUN chmod +x /opt/gow/eden-run.sh

# no bar at all: Eden is fullscreen, the bar showed up whenever a dialog took focus
RUN sed -i '/^bar swaybar_command waybar/d' /cfg/sway/config
COPY eden/sway-hide-dialogs.conf /tmp/sway-hide-dialogs.conf
RUN sed -i '/^# Need to autostart/e cat /tmp/sway-hide-dialogs.conf' /cfg/sway/config && rm /tmp/sway-hide-dialogs.conf

# gamepad combo -> Switch HOME, configurable from Wolfy
COPY common/home-combo.py /opt/gow/home-combo.py
COPY eden/stick-gyro.py /opt/gow/stick-gyro.py
RUN chmod +x /opt/gow/home-combo.py /opt/gow/stick-gyro.py

COPY eden/startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/startup-app.sh

ARG IMAGE_SOURCE
LABEL org.opencontainers.image.source=$IMAGE_SOURCE
