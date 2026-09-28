# Wolfy

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
- Le catalogue d'émulateurs est dans `backend/wolfy/emulators.py`. Les images locales sont construites
  depuis `images/<émulateur>/` (ce dépôt), sinon `/opt/stacks/wolf/images/<émulateur>/`.
  `images/eden` = image `wolfy-eden` de l'appli Switch (voir son README).

## Installation

### 1. Partager le socket de l'API Wolf

Par défaut Wolf crée son socket d'API dans son propre conteneur. Dans `/opt/stacks/wolf/compose.yaml` :

```yaml
services:
  wolf:
    environment:
      - WOLF_SOCKET_PATH=/var/run/wolf/wolf.sock   # ajouter
    volumes:
      - wolf-api:/var/run/wolf:rw                  # ajouter

volumes:
  wolf-api:                                        # ajouter
    name: wolf-api
```

puis `docker compose up -d` dans `/opt/stacks/wolf` (redémarre Wolf : à faire sans session en cours).

### 2. Lancer Wolfy

```bash
cd ~/Bureau/wolfy
cp .env.example .env        # puis choisir WOLFY_ADMIN_PASSWORD
docker compose up -d --build
```

Interface : <http://192.168.1.85:8420>

Wolfy peut arrêter Wolf et lancer des conteneurs via le socket Docker : ne l'expose pas sur Internet
sans reverse proxy HTTPS (swag) devant.

## Développement

```bash
# backend
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && WOLFY_ADMIN_PASSWORD=dev WOLFY_DATA=../data ../.venv/bin/uvicorn wolfy.main:app --reload --port 8420
# frontend (autre terminal) : http://localhost:5173, l'API est relayée vers :8420
cd frontend && npm install && npm run dev
```

Documentation interactive de l'API de Wolfy : `/api/docs`.
