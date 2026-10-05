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
| `build/` | Eden recompilé avec les correctifs de `build/patches/` (voir plus bas) |

`AppDir/` (Eden extrait, ≈300 Mo) n'est pas versionné : les AppImage ne se montent pas dans un
conteneur (pas de FUSE), il faut l'extraire sur l'hôte avant de construire :

```bash
cd images/eden
~/Applications/Eden-v0.2.1-amd64.AppImage --appimage-extract && rm -rf AppDir && mv squashfs-root AppDir
docker build -t wolfy-eden:latest .      # ou Wolfy > Émulateurs > Eden > Reconstruire
```

`/opt/stacks/wolf/images/eden` est un lien vers ce dossier.

## Eden corrigé

L'image remplace l'exécutable de l'AppImage par un Eden recompilé avec les correctifs de
`build/patches/` :

- `0001-open-preselected-user.patch` : le profil choisi dans « Qui joue ? » au lancement d'un
  jeu depuis le menu HOME devient l'utilisateur ouvert du service des comptes. Sans lui, les
  jeux (Mario Kart 8) gardaient le profil par défaut d'Eden (`current_user`), et donc sa
  sauvegarde.

`build/build.sh` compile la même version que l'AppImage (v0.2.1) dans un conteneur Arch
(clang, Qt 6.11, comme l'AppImage officielle) et range le résultat dans `patched/` (non
versionné) : `bin/eden` et, dans `lib/`, les bibliothèques plus récentes qu'il demande
(Boost 1.92, fmt 12.2, glibc 2.44). Le `Dockerfile` les copie par-dessus `/opt/eden/shared/`.

```bash
images/eden/build/build.sh          # ≈ 25 min la première fois, incrémental ensuite
cd images && docker build -f eden/Dockerfile -t wolfy-eden:latest .
```

Le dossier de build est gardé dans `~/.cache/wolfy-eden-build` (`WOLFY_EDEN_BUILD`). Après un
changement des paquets (Dockerfile de `build/`), effacer son `CMakeCache.txt` pour que la
configuration redétecte les dépendances. À chaque nouvelle version d'Eden : changer
`EDEN_TAG`, vérifier que les correctifs s'appliquent et que `patched/lib` couvre ce que le
nouvel exécutable demande à l'AppImage.
