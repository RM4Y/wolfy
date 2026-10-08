# EspBar on one ESP32 (Wi-Fi + Bluetooth), built by ../../build.sh
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/../components ${CMAKE_CURRENT_LIST_DIR}/../.cache/idf/components)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(espbar)
