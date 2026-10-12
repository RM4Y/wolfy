// EspBar on two ESP32, the Wi-Fi one: Wii Remotes over Bluetooth (the other ESP32, ../bt) ->
// UART -> Wi-Fi -> Wolfy -> Dolphin of the linked device's Wii session. See ../../../README.md.
#include "nvs_flash.h"

#include "config.h"
#include "link.h"
#include "radio.h"
#include "setup.h"

// the setup page: the Bluetooth ESP32 keeps its LED on, its button held 10 s closes it
void setup_poll(void) { radio_setup_poll(); }

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    static espbar_config_t cfg;
    bool setup = setup_requested();  // the Bluetooth ESP32's button held 10 s
    if (!config_load(&cfg) || setup)
        setup_run(&cfg);  // Wi-Fi from the setup page (or injected again from Wolfy)
    radio_start();  // the Bluetooth ESP32, flashed first when it doesn't run our build
    link_start(&cfg);
}
