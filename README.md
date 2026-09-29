# Wolfy Docker

Interface web d'administration pour [Wolf](https://games-on-whales.github.io/wolf/) (Games on Whales) :
le serveur de streaming Moonlight multi-sessions qui fait tourner les émulateurs (Switch, PlayStation, Wii…),
chacun dans son propre conteneur.

| Page | Ce qu'on y fait |
|---|---|
| **Tableau de bord** | État de Wolf, sessions actives, appareils, alerte quand un appareil demande l'appairage |
| **Appairage** | Saisie du code PIN Moonlight, nom des appareils, type de manette forcé, désappairage |
| **Sessions** | Sessions en cours (appli, appareil, résolution), arrêt d'une session |
| **Applications** | Les applis affichées dans Moonlight, ordre, ajout/suppression. « Configurer » ouvre la page de l'appli : tous les réglages de son émulateur (Eden : 800+ réglages de `qt-config.ini`, en onglets, en français) + le conteneur Wolf (image, ROMs, jaquette, montages, variables, options Docker) |
| **Émulateurs** | Catalogue (Eden, RetroArch, Dolphin…), état des images, construction/mise à jour |
| **Maintenance** | Redémarrer/arrêter Wolf, journaux, conteneurs d'applis, rapports de plantage, sauvegardes/restauration de `config.toml` |

## Architecture

```
navigateur ──► Wolfy (FastAPI + Vue 3, port 8420)
                 ├─ API Wolf ........ socket UNIX /var/run/wolf/wolf.sock (volume docker « wolf-api »)
                 │                    appairage, sessions, clients
                 ├─ config.toml ..... /opt/stacks/config/wolf/cfg (applications / profils)
                 ├─ qt-config.ini ... ~/.config/eden (réglages Eden)
                 └─ Docker .......... /var/run/docker.sock (redémarrage Wolf, conteneurs, images)
```

- **Modifier une application redémarre Wolf** : Wolf ne lit `config.toml` qu'au démarrage et le réécrit
  lui-même. Wolfy arrête donc Wolf, sauvegarde le fichier (`cfg/wolfy-backups/`, 30 conservées),
  applique la modification en gardant la mise en forme, puis relance Wolf. L'interface prévient s'il y a
  des sessions en cours.
- Les infos propres à Wolfy (noms des appareils, émulateur associé à chaque appli, notes) sont dans
  `data/wolfy.json`.
- Réglages Eden : `backend/wolfy/emulator_settings/eden.json` est généré depuis les sources d'Eden
  (types, valeurs par défaut, bornes, libellés et traduction française officielle) :
  `python3 tools/gen_eden_schema.py v0.2.1` (à relancer quand Eden est mis à jour). Wolfy modifie
  `~/.config/eden/qt-config.ini` ligne par ligne (sauvegardes dans `~/.config/eden/wolfy-backups/`) ;
  les sessions Wolf copient ce fichier à leur démarrage. Les réglages imposés par l'image Wolf
  (pseudo, IP du salon, moteur audio, interface réseau) sont affichés verrouillés.
- Réglages RetroArch : `backend/wolfy/emulator_settings/retroarch.json`, généré depuis les sources de
  RetroArch (configuration.c, menu_setting.c, traduction française) et des cœurs LRPS2 / PPSSPP :
  `python3 tools/gen_retroarch_schema.py v1.22.2`. Wolfy modifie `retroarch.cfg` et `config/<cœur>/<cœur>.opt`
  du RetroArch flatpak du PC (sauvegardes dans `wolfy-backups/`), refusé si RetroArch est ouvert sur le PC.
- Le catalogue d'émulateurs est dans `backend/wolfy/emulators.py`. Les images locales sont construites
  depuis `images/<émulateur>/` : `images/eden` = `wolfy-eden` (Switch, voir son README),
  `images/steam` = `wolfy-steam` (Steam, sur l'image officielle GoW : verrou de session, bibliothèques
  enregistrées dans `libraryfolders.vdf`, options de démarrage — `steam-setup.py`) ;
  `images/retroarch` = `wolfy-retroarch` (PlayStation) : cœurs LRPS2 / PPSSPP intégrés à l'image
  (`/opt/wolfy/cores`, dernières versions du buildbot libretro à la construction, liste dans
  `/opt/wolfy/cores/VERSIONS`) ; les playlists partagées sont copiées dans la session avec ces cœurs et
  les changements (scans, historique, favoris) réécrits vers celles du PC (`playlist-sync.py`).

## Installation

Une seule pile Docker (`compose.yaml`, projet `wolfy`) :

| Service | Rôle |
|---|---|
| `wolf` | Wolf (image officielle `ghcr.io/games-on-whales/wolf:stable`), réseau hôte, GPU NVIDIA |
| `wolfy` | cette interface, construite depuis le dépôt, port 8420 |
| `wolfy-eden`, `wolfy-retroarch`, `wolfy-steam` | images des applis Switch / PlayStation / Steam (profil `images`, construction seulement : Wolf les lance à chaque session) |

```bash
cd ~/Bureau/wolfy
cp .env.example .env                      # puis choisir WOLFY_ADMIN_PASSWORD
docker compose up -d --build              # Wolf + Wolfy
docker compose --profile images build     # images des émulateurs (ou Wolfy > Émulateurs)
```

Interface : <http://192.168.1.85:8420>

- État de Wolf (config.toml, jaquettes, appareils appairés) : `/opt/stacks/config/wolf`, inchangé.
- Données des émulateurs dans `config/` (jamais versionné) :
  `config/switch/keys` (prod.keys, title.keys — envoi depuis Émulateurs > Eden),
  `config/switch/nand` (firmware — installation d'un .zip depuis la même page, contenu installé),
  `config/switch/users` (profils `system/save` + sauvegardes `user/save`),
  `config/playstation/bios` (dossier « system » de RetroArch : BIOS PS2 dans `pcsx2/bios`, PS1, fichiers PPSSPP),
  `config/playstation/saves`, `config/playstation/states` ;
  `config/steam/data` (le `~/.steam` des sessions : installation, compte, réglages — une seule session
  Steam à la fois), `config/steam/wolfy/steam.json` (options de session) ;
  `config/<système>/wolfy/combo.json` : combinaisons de manette (menu / quitter).
  Eden sur le PC utilise les mêmes dossiers (`~/.local/share/eden/keys` est un lien vers
  `config/switch/keys`, la NAND et les sauvegardes sont réglées dans `~/.config/eden/qt-config.ini`).
- Le volume `nvidia-driver-vol` (pilote NVIDIA pour les conteneurs d'applis) est externe : à recréer
  après une mise à jour du pilote NVIDIA.
- Wolf et Wolfy partagent le socket d'API de Wolf via le volume `wolf-api`.
- Wolfy peut arrêter Wolf et lancer des conteneurs via le socket Docker, et voit le disque de l'hôte
  en lecture seule : ne l'expose pas sur Internet sans reverse proxy HTTPS (swag) devant.

Ancienne pile : `/opt/stacks/wolf/compose.yaml.migrated-to-wolfy` (retour arrière : `docker compose down`
ici, puis la renommer en `compose.yaml` et `docker compose up -d` dans `/opt/stacks/wolf`).

## Développement

```bash
# backend
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && WOLFY_ADMIN_PASSWORD=dev WOLFY_DATA=../data ../.venv/bin/uvicorn wolfy.main:app --reload --port 8420
# frontend (autre terminal) : http://localhost:5173, l'API est relayée vers :8420
cd frontend && npm install && npm run dev
```

Documentation interactive de l'API de Wolfy : `/api/docs`.
