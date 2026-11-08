#!/usr/bin/env python3
"""Updates the app Switch's emulator (the fork of emulator.version: Eglantine, or Lichii) to a newer
release, with Wolfy's patches applied again.

    update-emulator.py            newest release, if newer than emulator.version: build, then image
    update-emulator.py --check    only says whether a newer release exists (exit code 10 if so)
    update-emulator.py v0.1.0     that release (also to go back to an older one)

Steps: build.sh on the new sources (patches applied first: a patch that no longer applies stops
everything, the installed version is left as it was), then the image wolfy-switch:latest.
emulator.version is only rewritten once the new version has been built. Same as Wolfy ›
Émulateurs › Switch › Mettre à jour.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import emu_release as rel  # noqa: E402

IMAGE = "wolfy-switch:latest"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    tags = [a for a in argv if not a.startswith("-")]
    current = rel.read()
    name = current["EMU_NAME"]
    print(f"Installée : {name} {current.get('EMU_TAG', '?')} ({current.get('EMU_COMMIT', '?')[:9]})")
    published = ""
    if tags:
        tag = tags[0]
    else:
        latest = rel.latest(current)
        tag, published = latest["tag"], latest["published"]
        print(f"Dernière  : {tag}, publiée le {published[:10]} ({latest['url']})")
        if not rel.newer(latest, current):
            print(f"{name} est à jour.")
            return 0
        if check:
            print("Une mise à jour est disponible : relance sans --check pour l'installer.")
            return 10
    if check:
        return 0

    version = rel.version_for(tag, current, published)
    print(f"Mise à jour vers {name} {tag} ({version['EMU_COMMIT'][:9]}, clang {version['EMU_LLVM']}, "
          f"Qt {version['EMU_QT']})", flush=True)
    with tempfile.NamedTemporaryFile("w", suffix=".version") as f:
        f.write(rel.render(version))
        f.flush()
        subprocess.run([str(HERE / "build.sh")], check=True, env={**os.environ, "EMU_VERSION_FILE": f.name})
    print(f"Construction de l'image {IMAGE}", flush=True)
    subprocess.run(["docker", "build", "-f", "switch/Dockerfile", "-t", IMAGE, "."], cwd=HERE.parent, check=True)
    print(f"{name} {tag} installé : actif à la prochaine session Switch.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as exc:
        print(f"Échec ({exc.cmd[0]}, code {exc.returncode}) : la version installée n'a pas changé "
              "si l'échec vient de la compilation.", file=sys.stderr)
        sys.exit(1)
