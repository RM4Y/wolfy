idf_component_register(SRCS "main.c" "link.c" "wiimotes.c"
                       INCLUDE_DIRS "."
                       REQUIRES espbar_wire btstack esp_timer esp_app_format app_update nvs_flash driver)
