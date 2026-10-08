# bt_image.h / bt_image.bin: the Bluetooth ESP32's program, packed by ../../bt_image.py
set(bt_image ${CMAKE_CURRENT_LIST_DIR}/../../.cache/bt-image)
idf_component_register(SRCS "main.c" "config.c" "link.c" "radio.c"
                       INCLUDE_DIRS "." ${bt_image}
                       EMBED_FILES ${bt_image}/bt_image.bin
                       REQUIRES espbar_wire esp-serial-flasher esp_wifi esp_timer esp_netif nvs_flash esp_partition json driver tcp_transport mbedtls)
