#!/bin/bash
# PC gamepads chosen in Wolfy (Wii > Wolfy-Dolphin): their device nodes are created in this
# session by a root helper that lives as long as the session (see host-pads.py)
source /opt/gow/bash-lib/utils.sh
gow_log "Starting host-pads (PC gamepads for the Wii players)"
setsid python3 /opt/gow/host-pads.py >/proc/1/fd/1 2>&1 < /dev/null &
true
