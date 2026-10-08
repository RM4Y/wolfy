#include "radio.h"

#include <stdio.h>
#include <string.h>

#include "bt_image.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp32_port.h"
#include "esp_loader.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "link.h"
#include "wire.h"

// Wiring to the Bluetooth ESP32 (README.md): our TX2 -> its RX0, our RX2 <- its TX0,
// D25 -> its EN, and D26 -> its GPIO0 (BOOT) if it has that pin: only to write a Bluetooth ESP32
// that has no program of ours (else inject it once over USB from Wolfy)
#define UART UART_NUM_2
#define PIN_TX GPIO_NUM_17
#define PIN_RX GPIO_NUM_16
#define PIN_EN GPIO_NUM_25
#define PIN_BOOT GPIO_NUM_26
#define SILENCE_MS 6000  // it sends its stats every 2 s
#define RETRY_MS 10000   // after a failed flash (not wired?)
#define FLASH_BLOCK 1024
#define OTA_TRIES 2      // per start: then a Bluetooth ESP32 that answers is used as it is

extern const uint8_t bt_image_start[] asm("_binary_bt_image_bin_start");

const char *const radio_boards = "2";

static const char *TAG = "radio";
static wire_rx_t s_rx;
static volatile bool s_up;      // it runs our build: frames go through
static volatile bool s_hello;   // it answered EB_HELLO
static char s_id[BT_ID_LEN + 1];  // its build
static uint8_t s_addr[6];
static volatile bool s_have_addr;
static volatile int64_t s_last_rx;
static uint8_t s_scan;          // last EB_SCAN from Wolfy, given again after a reset
static uint8_t s_on;            // slots announced to Wolfy (bit per slot)
static volatile bool s_acked;   // EB_OTA_ACK received
static uint8_t s_ack_status;
static uint32_t s_ack_next;
static int s_ota_tries;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static char s_stats[EB_MAX_PAYLOAD + 1] = "carte Bluetooth : démarrage";

static void set_stats(const char *text, size_t len)
{
    if (len > EB_MAX_PAYLOAD)
        len = EB_MAX_PAYLOAD;
    portENTER_CRITICAL(&s_lock);
    memcpy(s_stats, text, len);
    s_stats[len] = 0;
    portEXIT_CRITICAL(&s_lock);
}

static void set_status(const char *text) { set_stats(text, strlen(text)); }

static void send_frame(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    uint8_t buf[WIRE_SIZE(EB_MAX_PAYLOAD)];
    uart_write_bytes(UART, buf, wire_encode(buf, type, slot, data, len));  // one frame at a time
}

// ---------------------------------------------------------------- link.h

void radio_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    if (type == EB_SCAN && len)
        s_scan = data[0];
    if (s_up && len <= EB_MAX_PAYLOAD)
        send_frame(type, slot, data, len);
}

void radio_stats(char *out, size_t size, uint32_t ms)
{
    portENTER_CRITICAL(&s_lock);
    strlcpy(out, s_stats, size);
    portEXIT_CRITICAL(&s_lock);
}

bool radio_bt_addr(uint8_t addr[6])
{
    if (s_have_addr)
        memcpy(addr, s_addr, 6);
    return s_have_addr;
}

// ---------------------------------------------------------------- frames from it

// Wolfy forgets the Wii Remotes of a Bluetooth ESP32 that restarted or went silent.
static void drop_all(void)
{
    for (int i = 0; i < EB_SLOTS; i++)
        if (s_on & 1 << i)
            link_send(EB_WIIMOTE_OFF, i, NULL, 0);
    s_on = 0;
}

static void on_frame(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    s_last_rx = esp_timer_get_time();
    switch (type) {
    case EB_HELLO:
        if (len < 6)
            break;
        memcpy(s_addr, data, 6);
        s_have_addr = true;
        len = len - 6 < BT_ID_LEN ? len - 6 : BT_ID_LEN;
        memcpy(s_id, data + 6, len);
        s_id[len] = 0;
        if (s_up && slot == 1) {  // it restarted by itself: its Wii Remotes are gone
            drop_all();
            send_frame(EB_SCAN, 0, &s_scan, 1);
        }
        s_hello = true;
        break;
    case EB_STATS:
        set_stats((const char *)data, len);
        break;
    case EB_OTA_ACK:
        if (len < 5)
            break;
        s_ack_status = data[0];
        s_ack_next = data[1] | data[2] << 8 | data[3] << 16 | (uint32_t)data[4] << 24;
        s_acked = true;
        break;
    case EB_WIIMOTE_ON:
    case EB_WIIMOTE_OFF:
    case EB_REPORT:
        if (!s_up || slot >= EB_SLOTS)
            break;
        if (type == EB_WIIMOTE_ON)
            s_on |= 1 << slot;
        else if (type == EB_WIIMOTE_OFF)
            s_on &= ~(1 << slot);
        link_send(type, slot, data, len);
        break;
    }
}

// Reads the UART for <ms> (or until *<until>).
static void pump(uint32_t ms, volatile bool *until)
{
    uint8_t buf[256];
    int64_t end = esp_timer_get_time() + ms * 1000LL;
    while (esp_timer_get_time() < end && !(until && *until)) {
        int n = uart_read_bytes(UART, buf, sizeof(buf), pdMS_TO_TICKS(10));
        if (n > 0)
            wire_feed(&s_rx, buf, n, on_frame);
    }
}

// Asks who it is for <ms>: true when it answered.
static bool ask_hello(uint32_t ms)
{
    s_hello = false;
    for (uint32_t t = 0; t < ms && !s_hello; t += 300) {
        send_frame(EB_HELLO, 0, NULL, 0);
        pump(300, &s_hello);
    }
    return s_hello;
}

// ---------------------------------------------------------------- updating it

static void reset_it(void)
{
    gpio_set_level(PIN_BOOT, 1);  // normal boot
    gpio_set_level(PIN_EN, 0);
    vTaskDelay(pdMS_TO_TICKS(100));
    gpio_set_level(PIN_EN, 1);
}

static bool wait_ack(uint32_t ms)
{
    s_acked = false;
    pump(ms, &s_acked);
    return s_acked && s_ack_status == 0;
}

static bool send_ota(uint8_t type, const uint8_t *data, uint16_t len, uint32_t ms)
{
    static uint8_t buf[WIRE_MAX];
    uart_write_bytes(UART, buf, wire_encode(buf, type, 0, data, len));
    return wait_ack(ms);
}

// Through its own program (it runs ours, another build): the new app into its other OTA slot,
// 1 KB at a time, each acknowledged. Needs no GPIO0.
static bool ota_it(void)
{
    const uint8_t *app = bt_image_start + BT_IMAGE_APP;
    uint32_t size = BT_IMAGE_SIZE - BT_IMAGE_APP;
    ESP_LOGW(TAG, "updating the Bluetooth ESP32 to build %s (%lu bytes)", BT_IMAGE_ID, (unsigned long)size);
    set_status("carte Bluetooth : mise à jour");
    uint8_t chunk[4 + EB_OTA_CHUNK] = {size, size >> 8, size >> 16, size >> 24};
    if (!send_ota(EB_OTA_BEGIN, chunk, 4, 20000))  // erases the slot first
        goto fail;
    s_ack_next = 0;
    for (int tries = 0; s_ack_next < size;) {
        uint32_t off = s_ack_next, n = size - off < EB_OTA_CHUNK ? size - off : EB_OTA_CHUNK;
        chunk[0] = off;
        chunk[1] = off >> 8;
        chunk[2] = off >> 16;
        chunk[3] = off >> 24;
        memcpy(chunk + 4, app + off, n);
        if (send_ota(EB_OTA_DATA, chunk, 4 + n, 1000))
            tries = 0;
        else if (s_acked || ++tries == 5)  // refused, or no answer 5 times in a row
            goto fail;
        else
            s_ack_next = off;
    }
    if (!send_ota(EB_OTA_END, NULL, 0, 5000))
        goto fail;
    ESP_LOGI(TAG, "Bluetooth ESP32 updated, restarting");
    return true;
fail:
    ESP_LOGE(TAG, "updating the Bluetooth ESP32 failed at %lu", (unsigned long)s_ack_next);
    return false;
}

// Through its ROM bootloader (it has no program of ours): BOOT low while EN is released, then
// esptool's stub at 921600 baud. Only when GPIO0 is wired.
static bool flash_it(void)
{
    ESP_LOGW(TAG, "flashing the Bluetooth ESP32 through its ROM (build %s, %u bytes)", BT_IMAGE_ID,
             BT_IMAGE_SIZE);
    set_status("carte Bluetooth : écriture");
    uart_set_baudrate(UART, 115200);
    esp32_port_t port = {
        .port.ops = &esp32_uart_ops,
        .baud_rate = 115200,
        .uart_port = UART,
        .uart_rx_pin = PIN_RX,
        .uart_tx_pin = PIN_TX,
        .reset_pin = PIN_EN,
        .boot_pin = PIN_BOOT,
        .dont_initialize_peripheral = true,  // our UART driver, kept
    };
    esp_loader_t loader;
    esp_loader_error_t err = esp_loader_init_serial(&loader, &port.port);
    esp_loader_connect_args_t connect = ESP_LOADER_CONNECT_DEFAULT();
    connect.trials = 3;  // no answer: GPIO0 not wired, most likely
    if (!err)
        err = esp_loader_connect_with_stub(&loader, &connect);
    if (!err)
        err = esp_loader_change_transmission_rate(&loader, WIRE_BAUD);
    esp_loader_flash_cfg_t cfg = {
        .offset = BT_IMAGE_OFFSET,
        .image_size = BT_IMAGE_SIZE,
        .block_size = FLASH_BLOCK,
    };
    if (!err)
        err = esp_loader_flash_start(&loader, &cfg);
    for (size_t done = 0; !err && done < BT_IMAGE_SIZE; done += FLASH_BLOCK) {
        size_t n = BT_IMAGE_SIZE - done < FLASH_BLOCK ? BT_IMAGE_SIZE - done : FLASH_BLOCK;
        err = esp_loader_flash_write(&loader, &cfg, bt_image_start + done, n);
    }
    if (!err)
        err = esp_loader_flash_finish(&loader, &cfg);  // checks the MD5
    esp_loader_deinit(&loader);
    uart_set_baudrate(UART, WIRE_BAUD);
    s_rx.len = 0;
    reset_it();
    if (err) {
        ESP_LOGE(TAG, "flashing the Bluetooth ESP32 failed (%d): GPIO0 not wired?", err);
        return false;
    }
    ESP_LOGI(TAG, "Bluetooth ESP32 flashed");
    return true;
}

// ---------------------------------------------------------------- task

static bool ours(void) { return s_hello && strcmp(s_id, BT_IMAGE_ID) == 0; }

// Is it there with our build? Asks, then restarts it and asks again (it says hello at boot).
// Another build of ours: updated through it; nothing of ours: through its ROM (GPIO0 wired).
static bool sync_it(void)
{
    if (!ask_hello(1200)) {
        reset_it();
        ask_hello(3000);
    }
    if (ours())
        return true;
    if (s_hello) {
        ESP_LOGW(TAG, "Bluetooth ESP32 runs build %s, we carry %s", s_id, BT_IMAGE_ID);
        if (s_ota_tries == OTA_TRIES)
            return true;  // not rewritten again and again: our frames are likely the same
        s_ota_tries++;
        if (ota_it() && ask_hello(8000) && ours())
            return true;
        // a new app that doesn't answer is undone by its bootloader at the next reset
        reset_it();
        if (ask_hello(3000) && ours())
            return true;
    }
    return flash_it() && ask_hello(4000) && ours();
}

static void radio_task(void *arg)
{
    for (;;) {
        if (!sync_it()) {
            set_status(s_hello ? "carte Bluetooth : mise à jour ratée"
                               : "carte Bluetooth absente ou à injecter en USB");
            vTaskDelay(pdMS_TO_TICKS(RETRY_MS));
            continue;
        }
        ESP_LOGI(TAG, "Bluetooth ESP32 ready, address %02x:%02x:%02x:%02x:%02x:%02x", s_addr[0], s_addr[1],
                 s_addr[2], s_addr[3], s_addr[4], s_addr[5]);
        set_status("carte Bluetooth prête");
        s_last_rx = esp_timer_get_time();
        s_up = true;
        radio_send(EB_SCAN, 0, &s_scan, 1);
        radio_send(EB_HELLO, 0, NULL, 0);  // announce its Wii Remotes
        while (esp_timer_get_time() - s_last_rx < SILENCE_MS * 1000LL)
            pump(100, NULL);
        ESP_LOGW(TAG, "Bluetooth ESP32 silent");
        s_up = false;
        drop_all();
    }
}

void radio_start(void)
{
    uart_config_t cfg = {
        .baud_rate = WIRE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART, 4096, 2048, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART, PIN_TX, PIN_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    // its RX0 is also driven by the USB-serial bridge of its DevKit: drive harder
    gpio_set_drive_capability(PIN_TX, GPIO_DRIVE_CAP_3);
    gpio_set_level(PIN_EN, 1);
    gpio_set_level(PIN_BOOT, 1);
    gpio_set_direction(PIN_EN, GPIO_MODE_OUTPUT);
    gpio_set_direction(PIN_BOOT, GPIO_MODE_OUTPUT);
    xTaskCreate(radio_task, "bt-esp", 6144, NULL, 6, NULL);
}
