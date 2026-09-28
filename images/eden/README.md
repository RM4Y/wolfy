# Image wolfy-eden

Image d'application Wolf « Switch » : Eden démarre sur le menu HOME de la Switch (`-qlaunch`),
avec une config par session, la connexion au salon local et les combinaisons de manette
(retour au menu HOME, quitter) réglables dans Wolfy.

| Fichier | Rôle |
|---|---|
| `Dockerfile` | base `ghcr.io/games-on-whales/base-app:edge` + Eden extrait |
| `startup-app.sh` | copie de la config Eden partagée, réglages forcés par session, lance le watcher |
| `eden-run.sh` | lance Eden et rejoint automatiquement le salon « Maison » |
| `home-combo.py` | combinaisons de la manette (HOME, quitter via Wolfy) |
| `sway-hide-dialogs.conf` | cache les boîtes de dialogue du salon |
| `20-fix-home-perms.sh` | droits des dossiers de config créés par Docker |

`AppDir/` (Eden extrait, ≈300 Mo) n'est pas versionné : les AppImage ne se montent pas dans un
conteneur (pas de FUSE), il faut l'extraire sur l'hôte avant de construire :

```bash
cd images/eden
~/Applications/Eden-v0.2.1-amd64.AppImage --appimage-extract && rm -rf AppDir && mv squashfs-root AppDir
docker build -t wolfy-eden:latest .      # ou Wolfy > Émulateurs > Eden > Reconstruire
```

`/opt/stacks/wolf/images/eden` est un lien vers ce dossier.
