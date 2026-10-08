#include "link.h"

#include <string.h>

#include "cJSON.h"
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/message_buffer.h"
#include "freertos/task.h"
#include "esp_crt_bundle.h"
#include "esp_system.h"
#include "esp_transport.h"
#include "esp_transport_ssl.h"
#include "esp_transport_tcp.h"
#include "esp_transport_ws.h"
#include "lwip/sockets.h"

#include "protocol.h"

#define VERSION "2"

// exported by tcp_transport but only declared in its private headers (ESP-IDF 5.3)
int esp_transport_get_socket(esp_transport_handle_t t);
#define LED GPIO_NUM_2  // blue LED of the DevKit: blinks = looking for Wolfy, on = linked
#define WIFI_UP BIT0

static const char *TAG = "link";
static espbar_config_t s_cfg;
static EventGroupHandle_t s_events;
static MessageBufferHandle_t s_out;
static volatile bool s_linked;

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_events, WIFI_UP);
        ESP_LOGW(TAG, "Wi-Fi lost, reconnecting");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = data;
        ESP_LOGI(TAG, "Wi-Fi up, IP " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(s_events, WIFI_UP);
    }
}

static void wifi_start(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL));
    wifi_config_t wc = {0};
    strlcpy((char *)wc.sta.ssid, s_cfg.ssid, sizeof(wc.sta.ssid));
    strlcpy((char *)wc.sta.password, s_cfg.password, sizeof(wc.sta.password));
    wc.sta.threshold.authmode = s_cfg.password[0] ? WIFI_AUTH_WPA_PSK : WIFI_AUTH_OPEN;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
}

static size_t frame(uint8_t *out, uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    uint16_t n = len + 2;
    out[0] = n & 0xff;
    out[1] = n >> 8;
    out[2] = type;
    out[3] = slot;
    if (len)
        memcpy(out + 4, data, len);
    return len + 4;
}

void link_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    if (!s_linked || len > EB_MAX_PAYLOAD)
        return;
    uint8_t buf[EB_MAX_PAYLOAD + 4];
    xMessageBufferSend(s_out, buf, frame(buf, type, slot, data, len), 0);
}

static bool ws_send(esp_transport_handle_t ws, const uint8_t *buf, size_t len)
{
    return esp_transport_ws_send_raw(ws, WS_TRANSPORT_OPCODES_BINARY | WS_TRANSPORT_OPCODES_FIN,
                                     (const char *)buf, len, 1000) == (int)len;
}

static bool send_hello(esp_transport_handle_t ws)
{
    uint8_t mac[6];
    char mac_str[18];
    esp_read_mac(mac, ESP_MAC_BT);
    snprintf(mac_str, sizeof(mac_str), "%02x:%02x:%02x:%02x:%02x:%02x", mac[0], mac[1], mac[2],
             mac[3], mac[4], mac[5]);
    cJSON *hello = cJSON_CreateObject();
    cJSON_AddStringToObject(hello, "role", "esp");
    cJSON_AddStringToObject(hello, "token", s_cfg.token);
    cJSON_AddStringToObject(hello, "version", VERSION);
    cJSON_AddStringToObject(hello, "mac", mac_str);
    char *text = cJSON_PrintUnformatted(hello);
    cJSON_Delete(hello);
    uint8_t buf[300];
    size_t len = strlen(text);
    bool ok = len <= sizeof(buf) - 4 && ws_send(ws, buf, frame(buf, EB_HELLO, 0, (uint8_t *)text, len));
    free(text);
    return ok;
}

// Bytes from Wolfy (WebSocket messages, frames may span them): complete frames go to BTstack.
static uint8_t s_rx[EB_MAX_PAYLOAD + 4];
static size_t s_rx_len;

static void feed(const uint8_t *data, size_t len)
{
    while (len) {
        size_t want = s_rx_len < 2 ? 2 : 2 + (s_rx[0] | s_rx[1] << 8);
        if (want > sizeof(s_rx)) {  // not a frame of ours: resync on the next message
            s_rx_len = 0;
            return;
        }
        size_t n = want - s_rx_len < len ? want - s_rx_len : len;
        memcpy(s_rx + s_rx_len, data, n);
        s_rx_len += n;
        data += n;
        len -= n;
        if (s_rx_len >= 4 && s_rx_len == 2 + (size_t)(s_rx[0] | s_rx[1] << 8)) {
            if (s_rx[2] != EB_PING)
                wiimotes_on_frame(s_rx[2], s_rx[3], s_rx + 4, s_rx_len - 4);
            s_rx_len = 0;
        }
    }
}

// One task does all the WebSocket I/O (TLS can't read and write from two tasks): connect,
// then alternately send BTstack's frames (+ a ping every 2 s) and read Wolfy's.
static void link_task(void *arg)
{
    esp_transport_handle_t parent;
    if (s_cfg.tls) {
        parent = esp_transport_ssl_init();
        esp_transport_ssl_crt_bundle_attach(parent, esp_crt_bundle_attach);
    } else {
        parent = esp_transport_tcp_init();
    }
    esp_transport_handle_t ws = esp_transport_ws_init(parent);
    esp_transport_ws_config_t ws_cfg = {.ws_path = s_cfg.path, .propagate_control_frames = true};
    esp_transport_ws_set_config(ws, &ws_cfg);
    uint8_t buf[256];
    uint8_t out[1024];  // frames waiting in s_out, sent as one WebSocket message

    for (;;) {
        gpio_set_level(LED, 0);
        xEventGroupWaitBits(s_events, WIFI_UP, false, true, portMAX_DELAY);
        if (esp_transport_connect(ws, s_cfg.host, s_cfg.port, 10000) < 0 || !send_hello(ws)) {
            ESP_LOGW(TAG, "Wolfy %s unreachable", s_cfg.url);
            esp_transport_close(ws);
            for (int i = 0; i < 6; i++) {  // 3 s of blinking before trying again
                gpio_set_level(LED, i & 1);
                vTaskDelay(pdMS_TO_TICKS(500));
            }
            continue;
        }
        // send each report at once: with Nagle a report waits for the ACK of the previous one,
        // and in modem sleep (required next to Bluetooth) ACKs only come at each DTIM beacon
        int fd = esp_transport_get_socket(ws), one = 1;
        if (fd >= 0)
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        ESP_LOGI(TAG, "linked to Wolfy %s (free heap %u)", s_cfg.url, (unsigned)esp_get_free_heap_size());
        gpio_set_level(LED, 1);
        s_rx_len = 0;
        xMessageBufferReset(s_out);
        s_linked = true;
        wiimotes_on_frame(EB_HELLO, 0, NULL, 0);  // resend the connected Wii Remotes
        TickType_t last_rx = xTaskGetTickCount(), last_ping = 0;
        bool ok = true;
        while (ok) {
            size_t n, used = 0;
            while (sizeof(out) - used >= EB_MAX_PAYLOAD + 4 &&
                   (n = xMessageBufferReceive(s_out, out + used, sizeof(out) - used, 0)) > 0)
                used += n;
            if (used)
                ok = ws_send(ws, out, used);
            TickType_t now = xTaskGetTickCount();
            if (ok && now - last_ping >= pdMS_TO_TICKS(2000)) {
                last_ping = now;
                ok = ws_send(ws, buf, frame(buf, EB_PING, 0, NULL, 0));
            }
            if (!ok)
                break;
            int r = esp_transport_read(ws, (char *)buf, sizeof(buf), 1);  // 1 ms: reports wait less
            if (r < 0)
                break;
            ws_transport_opcodes_t op = esp_transport_ws_get_read_opcode(ws) & 0x0f;
            if (r > 0) {
                last_rx = xTaskGetTickCount();
                if (op == WS_TRANSPORT_OPCODES_PING)
                    esp_transport_ws_send_raw(ws, WS_TRANSPORT_OPCODES_PONG | WS_TRANSPORT_OPCODES_FIN,
                                              (const char *)buf, r, 1000);
                else if (op == WS_TRANSPORT_OPCODES_CLOSE)
                    break;
                else if (op == WS_TRANSPORT_OPCODES_BINARY || op == WS_TRANSPORT_OPCODES_CONT)
                    feed(buf, r);
            } else if (op == WS_TRANSPORT_OPCODES_CLOSE) {
                break;
            }
            if (xTaskGetTickCount() - last_rx > pdMS_TO_TICKS(6000))  // Wolfy pings every 2 s
                break;
        }
        ESP_LOGW(TAG, "link to Wolfy lost");
        s_linked = false;
        esp_transport_close(ws);
        uint8_t off = 0;
        wiimotes_on_frame(EB_SCAN, 0, &off, 1);
    }
}

void link_start(const espbar_config_t *cfg)
{
    s_cfg = *cfg;
    s_events = xEventGroupCreate();
    s_out = xMessageBufferCreate(4096);
    gpio_reset_pin(LED);
    gpio_set_direction(LED, GPIO_MODE_OUTPUT);
    wifi_start();
    xTaskCreate(link_task, "wolfy", 8192, NULL, 5, NULL);
}
