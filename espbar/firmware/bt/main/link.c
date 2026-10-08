#include "link.h"

#include <string.h>

#include "driver/uart.h"
#include "esp_app_desc.h"
#include "esp_mac.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "wiimotes.h"
#include "wire.h"

#define UART UART_NUM_0  // TX0 / RX0, wired to the Wi-Fi ESP32
#define STATS_MS 2000

static wire_rx_t s_rx;
static bool s_valid;  // the Wi-Fi ESP32 talked to us: this program works, keep it

// ---------------------------------------------------------------- update (OTA)

static esp_ota_handle_t s_ota;
static const esp_partition_t *s_ota_part;
static uint32_t s_ota_size, s_ota_next;

static void ota_ack(uint8_t status)
{
    uint8_t ack[5] = {status, s_ota_next, s_ota_next >> 8, s_ota_next >> 16, s_ota_next >> 24};
    link_send(EB_OTA_ACK, 0, ack, sizeof(ack));
}

static uint32_t u32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

static void ota_abort(void)
{
    if (s_ota_part)
        esp_ota_abort(s_ota);
    s_ota_part = NULL;
}

// The new app, in order (a chunk sent again is acknowledged without being written again), then
// checked and booted. The bootloader goes back to this one if the new one never hears the Wi-Fi ESP32.
static void on_ota(uint8_t type, const uint8_t *data, uint16_t len)
{
    switch (type) {
    case EB_OTA_BEGIN:
        ota_abort();
        s_ota_next = 0;
        s_ota_size = len >= 4 ? u32(data) : 0;
        s_ota_part = esp_ota_get_next_update_partition(NULL);
        if (!s_ota_part || !s_ota_size || esp_ota_begin(s_ota_part, s_ota_size, &s_ota) != ESP_OK) {
            s_ota_part = NULL;
            ota_ack(1);
            return;
        }
        ota_ack(0);
        break;
    case EB_OTA_DATA:
        if (!s_ota_part || len < 4) {
            ota_ack(1);
            return;
        }
        if (u32(data) == s_ota_next && len > 4) {
            if (esp_ota_write(s_ota, data + 4, len - 4) != ESP_OK) {
                ota_abort();
                ota_ack(1);
                return;
            }
            s_ota_next += len - 4;
        }
        ota_ack(0);
        break;
    case EB_OTA_END: {
        bool ok = s_ota_part && s_ota_next == s_ota_size && esp_ota_end(s_ota) == ESP_OK &&
                  esp_ota_set_boot_partition(s_ota_part) == ESP_OK;
        if (!ok)
            ota_abort();
        s_ota_part = NULL;
        ota_ack(ok ? 0 : 1);
        if (ok) {
            uart_wait_tx_done(UART, pdMS_TO_TICKS(100));
            esp_restart();
        }
        break;
    }
    }
}

// ---------------------------------------------------------------- frames

void link_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    if (len > EB_MAX_PAYLOAD)
        return;
    uint8_t buf[WIRE_SIZE(EB_MAX_PAYLOAD)];
    uart_write_bytes(UART, buf, wire_encode(buf, type, slot, data, len));  // one frame at a time
}

// Our Bluetooth address and build: the Wi-Fi ESP32 flashes us when it carries another one.
// <boot>: we just started (our Wii Remotes are gone), else an answer to its HELLO.
static void send_hello(uint8_t boot)
{
    uint8_t payload[6 + BT_ID_LEN + 1];
    esp_read_mac(payload, ESP_MAC_BT);
    esp_app_get_elf_sha256((char *)payload + 6, BT_ID_LEN + 1);
    link_send(EB_HELLO, boot, payload, 6 + BT_ID_LEN);
}

static void on_frame(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    if (!s_valid) {
        s_valid = true;
        esp_ota_mark_app_valid_cancel_rollback();
    }
    if (type >= EB_OTA_BEGIN && type <= EB_OTA_END) {
        on_ota(type, data, len);
        return;
    }
    if (len > EB_MAX_PAYLOAD)
        return;
    if (type == EB_HELLO)
        send_hello(0);
    if (type != EB_PING)
        wiimotes_on_frame(type, slot, data, len);  // EB_HELLO: announce the Wii Remotes
}

// Frames from the Wi-Fi ESP32 (handled in this task: an update may block it), and our share of
// the stats every 2 s (it knows we're alive).
static void link_task(void *arg)
{
    uint8_t buf[256];
    TickType_t last_stats = xTaskGetTickCount();
    send_hello(1);
    for (;;) {
        int n = uart_read_bytes(UART, buf, sizeof(buf), pdMS_TO_TICKS(20));
        if (n > 0)
            wire_feed(&s_rx, buf, n, on_frame);
        TickType_t now = xTaskGetTickCount();
        if (now - last_stats >= pdMS_TO_TICKS(STATS_MS)) {
            char text[EB_MAX_PAYLOAD + 1];
            wiimotes_stats(text, sizeof(text), pdTICKS_TO_MS(now - last_stats));
            last_stats = now;
            link_send(EB_STATS, 0, (uint8_t *)text, strlen(text));
        }
    }
}

void link_start(void)
{
    uart_config_t cfg = {
        .baud_rate = WIRE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART, 2048, 4096, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART, 1, 3, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    xTaskCreate(link_task, "wifi-esp", 4096, NULL, 6, NULL);
}
