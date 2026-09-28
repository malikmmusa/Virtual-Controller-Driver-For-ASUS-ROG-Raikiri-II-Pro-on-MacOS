#!/bin/bash
# Start GeForce NOW with an SDL controller mapping for the Raikiri II Pro.
#
# GeForce NOW's bundled SDL reads extra mappings from the environment variable
# SDL_GAMECONTROLLERCONFIG. This script only sets that variable for this one
# launch: nothing is installed, patched or changed. Quit GeForce NOW to undo.
#
#   ./launch_gfn_with_mapping.sh            mapping only
#   ./launch_gfn_with_mapping.sh --no-mfi   also set SDL_JOYSTICK_MFI=0, so SDL
#                                           doesn't defer the Raikiri to Apple's
#                                           framework (see sdl_probe.py)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
app="${GFN_APP:-/Applications/GeForceNOW.app}"
binary="$app/Contents/MacOS/GeForceNOW"

if [ ! -x "$binary" ]; then
    echo "GeForce NOW not found at $app (set GFN_APP=/path/to/GeForceNOW.app)" >&2
    exit 1
fi
if pgrep -x GeForceNOW >/dev/null; then
    echo "GeForce NOW is already running. Quit it (Cmd-Q) and run this again." >&2
    exit 1
fi

SDL_GAMECONTROLLERCONFIG="$(grep -v '^[[:space:]]*#' "$here/raikiri_sdl_mapping.txt" | sed '/^[[:space:]]*$/d')"
export SDL_GAMECONTROLLERCONFIG
if [ "${1:-}" = "--no-mfi" ]; then
    export SDL_JOYSTICK_MFI=0
    echo "SDL_JOYSTICK_MFI=0"
fi

echo "Starting GeForce NOW with the Raikiri mapping. Leave this window open;"
echo "GeForce NOW's own log output appears below. Quit GeForce NOW to finish."
echo
exec "$binary"
