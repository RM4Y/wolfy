#!/bin/sh
# Builds the two EspBar programs that Wolfy injects into the ESP32 (merged images: bootloader +
# partitions + app, written at 0x0):
#   firmware.bin       one ESP32, Wi-Fi + Bluetooth (firmware/single)
#   firmware-dual.bin  two ESP32: the Wi-Fi one (firmware/wifi), carrying the Bluetooth one's
#                      program (firmware/bt), which it updates itself
#   firmware-bt.bin    the Bluetooth one, injected once over USB (when its GPIO0 isn't wired)
# Needs only Docker: ESP-IDF's official image, BTstack and esp-serial-flasher fetched into
# firmware/.cache (BTstack: free for non-commercial use, see its LICENSE).
set -e
cd "$(dirname "$0")"
IDF_IMAGE=espressif/idf:v5.3.2
BTSTACK_REF=v1.6.2
FLASHER_REF=v2.0.0

docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e BTSTACK_REF=$BTSTACK_REF -e FLASHER_REF=$FLASHER_REF \
    -v "$PWD":/espbar -w /espbar/firmware "$IDF_IMAGE" bash -ec '
  . $IDF_PATH/export.sh >/dev/null
  # BTstack as a component of these projects (integrate_btstack.py writes <IDF_PATH>/components)
  if [ ! -d .cache/idf/components/btstack ]; then
    rm -rf .cache/btstack .cache/idf && mkdir -p .cache/idf/components
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$BTSTACK_REF" \
        https://github.com/bluekitchen/btstack.git .cache/btstack
    (cd .cache/btstack/port/esp32 && IDF_PATH=/espbar/firmware/.cache/idf python integrate_btstack.py >/dev/null)
  fi
  # esp-serial-flasher: the Wi-Fi ESP32 flashes the Bluetooth one with it
  if [ ! -d .cache/esp-serial-flasher ]; then
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$FLASHER_REF" \
        https://github.com/espressif/esp-serial-flasher.git .cache/esp-serial-flasher
  fi

  build() {  # <project> <merged image> <offset of its first byte>
    mkdir -p "$(dirname "$2")"
    idf.py -C $1 -B .cache/build-$1 -DSDKCONFIG=/espbar/firmware/.cache/sdkconfig-$1 build
    (cd .cache/build-$1 && python -m esptool --chip esp32 merge_bin --target-offset $3 -o "$2" @flash_args)
  }
  build single /espbar/firmware.bin 0
  build bt /espbar/firmware/.cache/bt-image/merged.bin 0x1000
  (cd .cache/build-bt && python -m esptool --chip esp32 merge_bin -o /espbar/firmware-bt.bin @flash_args)
  python bt_image.py .cache/bt-image/merged.bin .cache/bt-image
  build wifi /espbar/firmware-dual.bin 0
'
ls -l firmware.bin firmware-dual.bin firmware-bt.bin
