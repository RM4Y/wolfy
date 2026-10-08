// EspBar on one ESP32: Wii Remotes over Bluetooth -> Wi-Fi -> Wolfy -> Dolphin of the linked
// device's Wii session. Both radios share the antenna (~37 reports/s per Wii Remote): two ESP32
// (../../wifi, ../../bt) get the full 100/s. See ../../../README.md.
#include "btstack_port_esp32.h"
#include "btstack_run_loop.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "config.h"
#include "link.h"
#include "wiimotes.h"

const char *const radio_boards = "1";

void radio_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    wiimotes_on_frame(type, slot, data, len);
}

void radio_stats(char *out, size_t size, uint32_t ms) { wiimotes_stats(out, size, ms); }

bool radio_bt_addr(uint8_t addr[6]) { return esp_read_mac(addr, ESP_MAC_BT) == ESP_OK; }

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
