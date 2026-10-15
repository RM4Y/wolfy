idf_component_register(SRCS "main.c" "link.c" "wiimotes.c"
                       INCLUDE_DIRS "."
                       REQUIRES espbar_wire btstack esp_timer esp_app_format app_update nvs_flash driver)
# the button and the LED are on the Wi-Fi ESP32 (EB_SEARCH)
target_compile_definitions(${COMPONENT_LIB} PRIVATE WIIMOTES_REMOTE_BUTTON)
