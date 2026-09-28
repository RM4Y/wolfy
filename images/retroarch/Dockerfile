# Wolf app image: RetroArch "PlayStation" (XMB menu, PS2 LRPS2 + PSP PPSSPP cores),
# sharing the host flatpak RetroArch setup mounted by Wolf.
FROM ghcr.io/games-on-whales/retroarch:edge

# no bar (RetroArch is fullscreen), hide the idle mouse cursor
RUN sed -i '/^bar swaybar_command waybar/d' /cfg/sway/config \
    && sed -i '/^# Need to autostart/i seat * hide_cursor 3000' /cfg/sway/config

COPY startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/startup-app.sh
