# Wolf app image: Steam (Big Picture) on the official Games on Whales image, with Wolfy's
# settings: shared Steam data (one login for every device, one session at a time),
# library folders registered automatically, startup mode / overlay / Proton log, combos.
# Build context: images/ (docker compose --profile images build, or Wolfy)
FROM ghcr.io/games-on-whales/steam:edge

# the image's own startup is kept and called by ours
RUN mv /opt/gow/startup-app.sh /opt/gow/steam-startup-gow.sh

COPY common/home-combo.py /opt/gow/home-combo.py
COPY steam/steam-setup.py /opt/gow/steam-setup.py
COPY steam/startup-app.sh /opt/gow/startup-app.sh
RUN chmod +x /opt/gow/home-combo.py /opt/gow/steam-setup.py /opt/gow/startup-app.sh /opt/gow/steam-startup-gow.sh
