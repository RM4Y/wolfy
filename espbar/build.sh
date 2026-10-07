#!/bin/sh
# Builds espbar/firmware.bin: the merged image (bootloader + partitions + app, written at 0x0)
# that Wolfy injects into the ESP32. Needs only Docker: ESP-IDF's official image, BTstack
# fetched into firmware/.cache (BTstack: free for non-commercial use, see its LICENSE).
set -e
cd "$(dirname "$0")"
IDF_IMAGE=espressif/idf:v5.3.2
BTSTACK_REF=v1.6.2

docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e BTSTACK_REF=$BTSTACK_REF \
    -v "$PWD":/espbar -w /espbar/firmware "$IDF_IMAGE" bash -ec '
  . $IDF_PATH/export.sh >/dev/null
  # BTstack as a component of this project (integrate_btstack.py writes <IDF_PATH>/components)
  if [ ! -d .cache/idf/components/btstack ]; then
    rm -rf .cache && mkdir -p .cache/idf/components
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$BTSTACK_REF" \
        https://github.com/bluekitchen/btstack.git .cache/btstack
    (cd .cache/btstack/port/esp32 && IDF_PATH=/espbar/firmware/.cache/idf python integrate_btstack.py >/dev/null)
  fi
  idf.py -B .cache/build -DEXTRA_COMPONENT_DIRS=/espbar/firmware/.cache/idf/components \
      -DSDKCONFIG=.cache/sdkconfig build
  cd .cache/build
  python -m esptool --chip esp32 merge_bin -o /espbar/firmware.bin @flash_args
'
ls -l firmware.bin
