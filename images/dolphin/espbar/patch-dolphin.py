#!/usr/bin/env python3
"""Adds the EspBar Wii Remotes (IOEspBar.cpp) to Dolphin's sources (argument: Dolphin's
source tree). WOLFY_NO_BLUEZ=1 leaves out the host's Bluetooth (Wii consoles 2+: the
host's real Wii Remotes belong to console 1). Fails if upstream changed the patched lines."""
import shutil
import sys
from pathlib import Path

src = Path(sys.argv[1])
here = Path(__file__).parent
real = src / "Source/Core/Core/HW/WiimoteReal"
for name in ("IOEspBar.h", "IOEspBar.cpp"):
    shutil.copy(here / name, real / name)


def patch(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if text.count(old) != 1:
        sys.exit(f"patch-dolphin: '{old.strip()}' not found once in {path}")
    path.write_text(text.replace(old, new))


cpp = real / "WiimoteReal.cpp"
patch(cpp, '#include "Core/HW/WiimoteReal/IOhidapi.h"\n',
      '#include "Core/HW/WiimoteReal/IOhidapi.h"\n#include "Core/HW/WiimoteReal/IOEspBar.h"\n#include <cstdlib>\n')
patch(cpp, "    m_backends.emplace_back(std::make_unique<WiimoteScannerLinux>());\n",
      '    if (!std::getenv("WOLFY_NO_BLUEZ"))\n'
      "      m_backends.emplace_back(std::make_unique<WiimoteScannerLinux>());\n")
patch(cpp, "    m_backends.emplace_back(std::make_unique<WiimoteScannerHidapi>());\n",
      "    m_backends.emplace_back(std::make_unique<WiimoteScannerHidapi>());\n"
      "    m_backends.emplace_back(std::make_unique<WiimoteScannerEspBar>());\n")
patch(src / "Source/Core/Core/CMakeLists.txt", "  HW/WiimoteReal/WiimoteReal.h\n",
      "  HW/WiimoteReal/WiimoteReal.h\n  HW/WiimoteReal/IOEspBar.cpp\n  HW/WiimoteReal/IOEspBar.h\n")
print("patch-dolphin: EspBar Wii Remotes added")
