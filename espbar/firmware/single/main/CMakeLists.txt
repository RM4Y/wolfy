# the Wolfy link of the Wi-Fi ESP32 and the Wii Remotes of the Bluetooth one, on one chip
idf_component_register(SRCS "main.c" "../../wifi/main/config.c" "../../wifi/main/link.c" "../../bt/main/wiimotes.c"
                       INCLUDE_DIRS "." "../../wifi/main" "../../bt/main"
                       REQUIRES espbar_wire btstack esp_wifi esp_timer esp_netif nvs_flash esp_partition json driver tcp_transport mbedtls)
