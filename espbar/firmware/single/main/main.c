// EspBar on one ESP32: Wii Remotes over Bluetooth -> Wi-Fi -> Wolfy -> Dolphin of the linked
// device's Wii session. Both radios share the antenna (~37 reports/s per Wii Remote): two ESP32
// (../../wifi, ../../bt) get the full 100/s. See ../../../README.md.
#include "btstack_port_esp32.h"
#include "btstack_run_loop.h"
#include "driver/gpio.h"
#include "esp_mac.h"
#include "nvs_flash.h"

#include "config.h"
#include "link.h"
#include "setup.h"
#include "wiimotes.h"

const char *const radio_boards = "1";

void radio_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    wiimotes_on_frame(type, slot, data, len);
}

void radio_stats(char *out, size_t size, uint32_t ms) { wiimotes_stats(out, size, ms); }

bool radio_bt_addr(uint8_t addr[6]) { return esp_read_mac(addr, ESP_MAC_BT) == ESP_OK; }

// The setup page runs alone (no Bluetooth): restart into it.
void setup_request(void) { setup_reboot(true); }

// While it is up: LED on, the button held 10 s again closes it (once released after opening it).
void setup_poll(void)
{
    static bool started, armed;
    static uint32_t held;  // ms
    if (!started) {
        gpio_reset_pin(WIIMOTES_BUTTON);
        gpio_set_direction(WIIMOTES_BUTTON, GPIO_MODE_INPUT);
        gpio_set_pull_mode(WIIMOTES_BUTTON, GPIO_PULLDOWN_ONLY);
        gpio_reset_pin(WIIMOTES_LED);
        gpio_set_direction(WIIMOTES_LED, GPIO_MODE_OUTPUT);
        started = true;
    }
    bool pressed = gpio_get_level(WIIMOTES_BUTTON);
    armed |= !pressed;
    held = pressed && armed ? held + 100 : 0;
    if (held >= SETUP_HOLD_MS)
        setup_reboot(false);
    gpio_set_level(WIIMOTES_LED, held ? held % 1000 < 300 : 1);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    static espbar_config_t cfg;
    bool setup = setup_requested();  // the button held 10 s
    if (!config_load(&cfg) || setup)
        setup_run(&cfg);  // Wi-Fi from the setup page (or injected again from Wolfy)
    link_start(&cfg);

    btstack_init();
    wiimotes_init();
    btstack_run_loop_execute();  // forever
}
