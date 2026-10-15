#include "button.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "link.h"
#include "protocol.h"
#include "setup.h"

// The button (D4 to 3V3) and the LED (D15) of the EspBar, as ../../bt/main/wiimotes.h on one ESP32:
// held 3 s and released, the Bluetooth ESP32 looks for Wii Remotes for 30 s (EB_SEARCH), the LED
// blinks meanwhile; held 10 s, the setup page. The LED blinks once a second while it is held.
#define BUTTON GPIO_NUM_4
#define LED GPIO_NUM_15
#define BUTTON_HOLD_MS 3000
#define SETUP_HOLD_MS 10000
#define SEARCH_MS 30000  // as long as the Bluetooth ESP32 looks
#define TICK_MS 50

static const char *TAG = "button";

static void pins(void)
{
    gpio_reset_pin(BUTTON);
    gpio_set_direction(BUTTON, GPIO_MODE_INPUT);
    gpio_set_pull_mode(BUTTON, GPIO_PULLDOWN_ONLY);
    gpio_reset_pin(LED);
    gpio_set_direction(LED, GPIO_MODE_OUTPUT);
    gpio_set_level(LED, 0);
}

static void button_task(void *arg)
{
    uint32_t held = 0, search_left = 0, ticks = 0;  // ms, ms
    for (;;) {
        ticks++;
        if (gpio_get_level(BUTTON)) {
            held += TICK_MS;
            if (held == SETUP_HOLD_MS) {
                ESP_LOGI(TAG, "setup page");
                gpio_set_level(LED, 1);
                setup_reboot(true);
            }
        } else {
            if (held >= BUTTON_HOLD_MS && held < SETUP_HOLD_MS) {
                ESP_LOGI(TAG, "search for %d s", SEARCH_MS / 1000);
                radio_send(EB_SEARCH, 0, NULL, 0);
                search_left = SEARCH_MS;
            }
            held = 0;
        }
        if (search_left)
            search_left = search_left > TICK_MS ? search_left - TICK_MS : 0;
        bool led;
        if (held)
            led = held % 1000 < 300;  // one blink per second held
        else
            led = search_left && (ticks / 3) % 2;  // ~3 blinks per second
        gpio_set_level(LED, led);
        vTaskDelay(pdMS_TO_TICKS(TICK_MS));
    }
}

void button_start(void)
{
    pins();
    xTaskCreate(button_task, "button", 2560, NULL, 4, NULL);
}

// While it is up: LED on, the button held 10 s again closes it (once released after opening it).
void button_setup_poll(void)
{
    static bool started, armed;
    static uint32_t held;  // ms
    if (!started) {
        pins();
        started = true;
    }
    bool pressed = gpio_get_level(BUTTON);
    armed |= !pressed;
    held = pressed && armed ? held + 100 : 0;
    if (held >= SETUP_HOLD_MS)
        setup_reboot(false);
    gpio_set_level(LED, held ? held % 1000 < 300 : 1);
}
