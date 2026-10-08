// EspBar on two ESP32, the Bluetooth one: Wii Remotes over Bluetooth -> UART -> the Wi-Fi ESP32
// (../wifi) -> Wolfy. Alone on the radio, the Wii Remotes send their 100 reports/s.
// See ../../../README.md.
#include "btstack_port_esp32.h"
#include "btstack_run_loop.h"
#include "nvs_flash.h"

#include "link.h"
#include "wiimotes.h"

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    link_start();
    btstack_init();
    wiimotes_init();
    btstack_run_loop_execute();  // forever
}
