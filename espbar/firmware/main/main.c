// EspBar: Wii Remotes over Bluetooth -> Wi-Fi -> Wolfy -> Dolphin of the linked device's
// Wii session. See ../../README.md.
#include "btstack_port_esp32.h"
#include "btstack_run_loop.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "config.h"
#include "link.h"
#include "wiimotes.h"

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
    link_start(&cfg);

    btstack_init();
    wiimotes_init();
    btstack_run_loop_execute();  // forever
}
