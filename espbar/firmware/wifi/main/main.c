// EspBar on two ESP32, the Wi-Fi one: Wii Remotes over Bluetooth (the other ESP32, ../bt) ->
// UART -> Wi-Fi -> Wolfy -> Dolphin of the linked device's Wii session. See ../../../README.md.
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "config.h"
#include "link.h"
#include "radio.h"

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    static espbar_config_t cfg;
    if (!config_load(&cfg)) {
        for (;;)
            vTaskDelay(portMAX_DELAY);  // nothing to do without Wi-Fi: inject it again from Wolfy
    }
    radio_start();  // the Bluetooth ESP32, flashed first when it doesn't run our build
    link_start(&cfg);
}
