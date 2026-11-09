#!/usr/bin/env python3
"""HOME menu and games of the Switch session, each in a Eglantine process of its own.

    wolfy-launcher.py <AppRun>

The menu (Eglantine -qlaunch, WOLFY_LAUNCHER_ROLE=menu) never runs a game: it tracks a placeholder
of it (no guest code), so it shows it suspended, resumes and closes it as on a Switch. Files in
WOLFY_LAUNCHER_DIR (patch 0004-wolfy-launcher):
  menu -> here: "launch" (program id, user index, file): start the game in a new process
                (-f -u <user> -g <file>), which boots it like on its own (Switch 1 or 2 mode, its
                counter, nothing of a previous game); "resume": the menu brought the game to the
                foreground; "close": the menu closed it
  game -> here: "home": HOME pressed in the game
  here -> menu: "menu-home": press HOME in the menu; "game-ended": the game is gone

The process in the background is stopped (SIGSTOP): both read the same pads, and a stopped game
keeps its state. The session ends with the menu.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DIR = Path(os.environ.get("WOLFY_LAUNCHER_DIR", "/tmp/wolfy-launcher"))
CFG_DIR = Path.home() / ".config/eden"


def log(msg: str) -> None:
    print(f"[wolfy-launcher] {msg}", flush=True)


def descendants(pid: int) -> set[int]:
    """pid and all its children (AppRun may start Eglantine as a child)."""
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            ppid = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(entry.name))
    found, todo = set(), [pid]
    while todo:
        p = todo.pop()
        if p not in found:
            found.add(p)
            todo.extend(children.get(p, []))
    return found


def sway_windows() -> list[dict]:
    """Windows of the sway tree, with their workspace."""
    try:
        tree = json.loads(subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True,
                                         text=True, timeout=5).stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return []
    found = []

    def walk(node, workspace):
        if node.get("type") == "workspace":
            workspace = node.get("name")
        if node.get("type") in ("con", "floating_con") and not node.get("nodes") \
                and node.get("pid"):
            found.append({"id": node["id"], "pid": node["pid"], "workspace": workspace,
                          "floating": node.get("type") == "floating_con",
                          "name": node.get("name"), "focused": node.get("focused"),
                          "fullscreen": node.get("fullscreen_mode")})
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child, workspace)

    walk(tree, None)
    return found


def sway(command: str) -> None:
    r = subprocess.run(["swaymsg", command], capture_output=True, text=True, timeout=5)
    if r.returncode != 0 or '"success": false' in r.stdout:
        log(f"swaymsg {command!r}: {r.stdout.strip()} {r.stderr.strip()}")


def log_windows(when: str) -> None:
    for w in sway_windows():
        log(f"  {when}: window {w['id']} pid {w['pid']} '{w['name']}' workspace "
            f"{w['workspace']} focused={w['focused']} fullscreen={w['fullscreen']}")


def configure_pads() -> None:
    """Players 1-4 = the pads of the session (pad-config.py), read by the process started next."""
    try:
        subprocess.run([sys.executable, "/opt/gow/pad-config.py", str(CFG_DIR / "qt-config.ini")],
                       timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"pad-config failed: {e}")


class Eglantine:
    def __init__(self, apprun: str, role: str, args: list[str], program_id: str = ""):
        configure_pads()
        env = dict(os.environ, WOLFY_LAUNCHER_ROLE=role, WOLFY_LAUNCHER_DIR=str(DIR))
        self.role, self.program_id = role, program_id
        self.proc = subprocess.Popen([apprun, *args], env=env, start_new_session=True)
        self.stopped = False
        log(f"{role} started (pid {self.proc.pid}): {' '.join(args)}")

    def alive(self) -> bool:
        return self.proc.poll() is None

    def signal(self, sig: int) -> None:
        try:
            os.killpg(self.proc.pid, sig)
        except ProcessLookupError:
            pass

    def stop(self) -> None:
        if not self.stopped and self.alive():
            self.signal(signal.SIGSTOP)
            self.stopped = True

    def resume(self) -> None:
        if self.stopped:
            self.signal(signal.SIGCONT)
            self.stopped = False

    def windows(self) -> list[dict]:
        pids = descendants(self.proc.pid)
        return [w for w in sway_windows() if w["pid"] in pids]

    def show(self) -> None:
        """Its windows go to its own workspace (by sway id: no criteria on X11 pids), shown."""
        for w in self.windows():
            if w["workspace"] != self.role:
                sway(f"[con_id={w['id']}] move container to workspace {self.role}")
        sway(f"workspace {self.role}")
        # main window fullscreen; dialogs (the profile selector) stay floating, focused last
        windows = sorted(self.windows(), key=lambda w: w["floating"])
        for w in windows:
            sway(f"[con_id={w['id']}] focus")
            if not w["floating"]:
                sway(f"[con_id={w['id']}] fullscreen enable")

    def close(self) -> None:
        """Ends the process: asked first (SIGTERM), killed after 10 s."""
        self.resume()
        self.signal(signal.SIGTERM)
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.signal(signal.SIGKILL)
            self.proc.wait()
        log(f"{self.role} {self.program_id} closed")


def put(name: str, content: str = "") -> None:
    """A request to the menu, written at once."""
    tmp = DIR / f"{name}.tmp"
    tmp.write_text(content)
    tmp.rename(DIR / name)


def take(name: str) -> list[str] | None:
    """Lines of a request file, removed once read."""
    path = DIR / name
    try:
        lines = path.read_text().splitlines()
        path.unlink()
        return lines
    except FileNotFoundError:
        return None


def main(apprun: str) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    for name in ("launch", "resume", "close", "home", "menu-home", "game-ended"):
        (DIR / name).unlink(missing_ok=True)
    menu = Eglantine(apprun, "menu", ["--", "-qlaunch"])
    game: Eglantine | None = None
    pending_show = 0.0  # a game was started: show it once its window is there

    def show_menu() -> None:
        menu.resume()
        menu.show()
        log_windows("menu shown")

    def show_game() -> None:
        game.resume()
        game.show()
        log_windows("game shown")
        menu.stop()

    last_check = 0.0
    while menu.alive():
        time.sleep(0.1)

        # The window shown stays fullscreen: sway gives it back a border when it leaves it (a
        # window closing on another workspace, a client resizing itself).
        if time.monotonic() - last_check > 1.0 and not pending_show:
            last_check = time.monotonic()
            shown = game if game is not None and game.alive() and not game.stopped else menu
            for w in shown.windows():
                if not w["fullscreen"] and not w["floating"]:
                    log(f"{shown.role} window {w['id']} left fullscreen: back to it")
                    sway(f"[con_id={w['id']}] fullscreen enable")

        if take("close") is not None and game is not None:
            log(f"the menu closed {game.program_id}")
            game.close()
            game, pending_show = None, 0.0
            show_menu()

        launch = take("launch")
        if launch and len(launch) >= 3:
            program_id, user, path = launch[0], launch[1], launch[2]
            if game is not None:
                game.close()
            # -f: with a game to boot, Eglantine only goes fullscreen when asked here. -u: the user
            # picked in the menu ("Who is playing?")
            game = Eglantine(apprun, "game", ["-f", "-u", user, "-g", path], program_id)
            pending_show = time.monotonic()

        resume = take("resume")
        if resume and game is not None and game.alive() and not pending_show \
                and resume[0] == game.program_id:
            log(f"resuming {game.program_id}")
            show_game()

        if pending_show and game is not None:
            if game.windows() and time.monotonic() - pending_show > 1.0:
                pending_show = 0.0
                show_game()
            elif time.monotonic() - pending_show > 60:
                pending_show = 0.0
                log(f"no window for {game.program_id} after 60 s")

        if take("home") is not None and game is not None and game.alive():
            log(f"HOME: {game.program_id} paused, menu shown")
            game.stop()
            put("menu-home")
            show_menu()

        if game is not None and not game.alive():
            log(f"{game.program_id} ended (code {game.proc.returncode}), menu shown")
            game, pending_show = None, 0.0
            put("game-ended")
            show_menu()

    log(f"menu ended (code {menu.proc.returncode})")
    if game is not None:
        game.close()


if __name__ == "__main__":
    main(sys.argv[1])
