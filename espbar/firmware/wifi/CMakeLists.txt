# EspBar on two ESP32: the Wi-Fi one, which carries and flashes the Bluetooth one (../bt),
# built by ../../build.sh
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/../components ${CMAKE_CURRENT_LIST_DIR}/../.cache/esp-serial-flasher)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(espbar-wifi)
