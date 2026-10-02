#!/usr/bin/env python3
"""RPCS3 input config of this session: one PS3 player per gamepad of the session.

RPCS3 names its SDL gamepads "<SDL name> <n>" (n = rank among the pads with that name, in SDL's
order): this lists them with RPCS3's own SDL library and the same SDL hints, then writes an
input config where each player uses the SDL handler with RPCS3's default SDL mapping (only
Handler and Device are written: RPCS3 fills in the handler's defaults).

    rpcs3-pads.py <input_configs/global/NAME.yml>    (rpcs3 --input-config NAME)
"""
import ctypes
import os
import sys

SDL_LIB = "/opt/rpcs3/usr/lib/libSDL3.so.0"
SDL_INIT_GAMEPAD = 0x2000
PLAYERS = 7


def gamepads() -> list[str]:
    os.environ.setdefault("SDL_JOYSTICK_THREAD", "1")
    os.environ.setdefault("SDL_JOYSTICK_HIDAPI_PS3", "1")
    sdl = ctypes.CDLL(SDL_LIB)
    sdl.SDL_Init.argtypes = [ctypes.c_uint32]
    sdl.SDL_Init.restype = ctypes.c_bool
    sdl.SDL_GetGamepads.argtypes = [ctypes.POINTER(ctypes.c_int)]
    sdl.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
    sdl.SDL_GetGamepadNameForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetGamepadNameForID.restype = ctypes.c_char_p
    if not sdl.SDL_Init(SDL_INIT_GAMEPAD):
        return []
    count = ctypes.c_int()
    ids = sdl.SDL_GetGamepads(ctypes.byref(count))
    names, seen = [], {}
    for i in range(count.value):
        raw = sdl.SDL_GetGamepadNameForID(ids[i])
        name = raw.decode(errors="replace") if raw else "Unknown"
        seen[name] = seen.get(name, 0) + 1
        names.append(f"{name} {seen[name]}")
    sdl.SDL_Quit()
    return names


def quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main(out: str) -> None:
    pads = gamepads()
    lines = []
    for i in range(PLAYERS):
        lines.append(f"Player {i + 1} Input:")
        if i < len(pads):
            lines += ["  Handler: SDL", f"  Device: {quote(pads[i])}"]
        else:
            lines += ['  Handler: "Null"', '  Device: "Null"']
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[rpcs3-pads] {out}: {pads or 'aucune manette'}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
