idf_component_register(SRCS "main.c" "config.c" "link.c" "wiimotes.c"
                       INCLUDE_DIRS "."
                       REQUIRES btstack esp_wifi esp_netif nvs_flash esp_partition json driver tcp_transport mbedtls)
