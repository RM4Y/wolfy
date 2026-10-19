#include "wiimotes.h"

#include <string.h>

#include <stdio.h>

#include "btstack.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#include "protocol.h"

static const char *TAG = "wiimotes";

#define COD_WIIMOTE 0x002504     // RVL-CNT-01 and Balance Board
#define COD_WIIMOTE_TR 0x000508  // RVL-CNT-01-TR (MotionPlus inside)
#define INQUIRY_LENGTH 3         // x 1.28 s
#define OUT_QUEUE 16
// Search: during the linked device's Wii session while no Wii Remote is connected, or for 30 s
// after the button (D4 to 3V3) is held 3 s and released (to add one). Not otherwise: an inquiry
// takes the radio from the connected Wii Remotes (their reports drop from ~37 to ~25/s).
// Held 10 s: the Wi-Fi setup page. The LED blinks once a second while it is held.
// Two ESP32: the button and the LED are on the Wi-Fi one, which sends EB_SEARCH (bt/main/CMakeLists.txt).
#define BUTTON WIIMOTES_BUTTON
#define SEARCH_LED WIIMOTES_LED  // blinks while searching, on while the setup page is up
#ifdef WIIMOTES_REMOTE_BUTTON
#define button_pressed() false
#define set_led(on) ((void)(on))
#else
#define button_pressed() gpio_get_level(BUTTON)
#define set_led(on) gpio_set_level(SEARCH_LED, on)
#endif
#define BUTTON_HOLD_MS 3000
#define SETUP_ALIVE_MS 3000  // the Wi-Fi ESP32 says its setup page is up every second
#define SETUP_BOOT_MS 8000   // LED on while the Wi-Fi ESP32 restarts into it (no dark gap)
#define SEARCH_MS 30000
#define TICK_MS 50

typedef struct {
    bool used;
    bool ready;  // both HID channels open, announced to Wolfy
    bool pairing;  // found by the search, its HID control channel asks for pairing first
    bd_addr_t addr;
    hci_con_handle_t handle;
    uint16_t ctrl_cid, intr_cid;
    uint8_t out[OUT_QUEUE][EB_MAX_PAYLOAD];  // output reports waiting for the radio
    uint8_t out_len[OUT_QUEUE];
    uint8_t out_head, out_count;
} wiimote_t;

static wiimote_t s_wm[EB_SLOTS];
static bool s_scan;        // the linked device's Wii session is up (Wolfy wants Wii Remotes)
static bool s_inquiring;
static uint32_t s_search_left;  // ms of search left (button)
static uint32_t s_button_held;  // ms
static uint32_t s_setup_left;   // ms: the setup page is up (two ESP32: told by the Wi-Fi one)
static btstack_timer_source_t s_tick;
static uint32_t s_ticks;
static bool s_connecting;  // an outgoing connection is being set up (one at a time)
static bool s_have_candidate;
static bd_addr_t s_candidate;
static btstack_timer_source_t s_retry_timer;
static btstack_packet_callback_registration_t s_hci_cb;

// reports from the Wii Remotes since the last wiimotes_stats(), longest wait between two (us)
static uint32_t s_bt_reports;
// shown in the stats (no log here: UART0 is the link to the Wi-Fi ESP32)
static const char *s_last_link = "-";  // how the last Wii Remote came (search or by itself)
static const char *s_pairing = "-";    // the last pairing (ok / ko)
static uint32_t s_calls;               // incoming Bluetooth connections (a paired Wii Remote waking up)
static int s_call_status = -1;         // HCI status of the last one (0: connected)
static bool s_call_pending;
static int64_t s_bt_last, s_bt_gap;

// ---------------------------------------------------------------- frames from Wolfy

typedef struct {
    uint8_t type, slot, len;
    uint8_t data[EB_MAX_PAYLOAD];
} inbound_t;

static QueueHandle_t s_in;
static volatile bool s_in_scheduled;
static btstack_context_callback_registration_t s_in_cb;

static void handle_frame(const inbound_t *f);

static void drain_inbound(void *ctx)
{
    s_in_scheduled = false;
    inbound_t f;
    while (xQueueReceive(s_in, &f, 0))
        handle_frame(&f);
}

void wiimotes_on_frame(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    inbound_t f = {.type = type, .slot = slot, .len = len > EB_MAX_PAYLOAD ? EB_MAX_PAYLOAD : len};
    if (f.len)
        memcpy(f.data, data, f.len);
    if (xQueueSend(s_in, &f, 0) != pdTRUE)
        return;  // full: an output report is lost, the game sends more
    if (!s_in_scheduled) {
        s_in_scheduled = true;
        btstack_run_loop_execute_on_main_thread(&s_in_cb);
    }
}

// ---------------------------------------------------------------- slots

static int free_slots(void)
{
    int n = 0;
    for (int i = 0; i < EB_SLOTS; i++)
        n += !s_wm[i].used;
    return n;
}

static wiimote_t *by_addr(const bd_addr_t addr)
{
    for (int i = 0; i < EB_SLOTS; i++)
        if (s_wm[i].used && bd_addr_cmp(s_wm[i].addr, addr) == 0)
            return &s_wm[i];
    return NULL;
}

static wiimote_t *by_cid(uint16_t cid)
{
    for (int i = 0; i < EB_SLOTS; i++)
        if (s_wm[i].used && cid && (s_wm[i].ctrl_cid == cid || s_wm[i].intr_cid == cid))
            return &s_wm[i];
    return NULL;
}

static wiimote_t *alloc(const bd_addr_t addr)
{
    for (int i = 0; i < EB_SLOTS; i++)
        if (!s_wm[i].used) {
            memset(&s_wm[i], 0, sizeof(s_wm[i]));
            s_wm[i].used = true;
            s_wm[i].handle = HCI_CON_HANDLE_INVALID;
            bd_addr_copy(s_wm[i].addr, addr);
            return &s_wm[i];
        }
    return NULL;
}

static uint8_t slot_of(const wiimote_t *w) { return (uint8_t)(w - s_wm); }

static void announce(wiimote_t *w)
{
    link_send(EB_WIIMOTE_ON, slot_of(w), w->addr, 6);
}

static void release(wiimote_t *w)
{
    if (w->ready) {
        ESP_LOGI(TAG, "Wii Remote %s gone (slot %d)", bd_addr_to_str(w->addr), slot_of(w) + 1);
        link_send(EB_WIIMOTE_OFF, slot_of(w), NULL, 0);
    }
    memset(w, 0, sizeof(*w));
}

// ---------------------------------------------------------------- inquiry / connection

static void schedule_inquiry(uint32_t ms);

// only with the button: no search by itself during a Wii session
static bool want_search(void) { return s_search_left; }

static void start_inquiry(void);

static void start_search(void)
{
    ESP_LOGI(TAG, "search for %d s", SEARCH_MS / 1000);
    s_search_left = SEARCH_MS;
    start_inquiry();
}

static void start_inquiry(void)
{
    if (!want_search() || s_inquiring || s_connecting || !free_slots())
        return;
    if (gap_inquiry_start(INQUIRY_LENGTH) == 0)
        s_inquiring = true;
    else
        schedule_inquiry(1000);
}

static void retry_cb(btstack_timer_source_t *ts) { start_inquiry(); }

static void schedule_inquiry(uint32_t ms)
{
    btstack_run_loop_remove_timer(&s_retry_timer);
    btstack_run_loop_set_timer_handler(&s_retry_timer, retry_cb);
    btstack_run_loop_set_timer(&s_retry_timer, ms);
    btstack_run_loop_add_timer(&s_retry_timer);
}

static void l2cap_handler(uint8_t type, uint16_t channel, uint8_t *packet, uint16_t size);

static void connect_candidate(void)
{
    s_have_candidate = false;
    if (by_addr(s_candidate) || !free_slots()) {
        schedule_inquiry(200);
        return;
    }
    wiimote_t *w = alloc(s_candidate);
    ESP_LOGI(TAG, "connecting to Wii Remote %s", bd_addr_to_str(w->addr));
    s_connecting = true;
    // Pair before the HID channels, as BlueZ does: a Wii Remote woken with SYNC then remembers us
    // and comes back by itself at any button (it doesn't when paired after them). The channel
    // takes the security level asked when it is created. Woken with 1 + 2, the pairing fails
    // (PIN: hci_handler): channel_opened() connects it again without.
    w->pairing = true;
    gap_drop_link_key_for_bd_addr(w->addr);  // a fresh pairing: its key may be stale (paired elsewhere)
    gap_set_security_level(LEVEL_2);
    uint8_t err = l2cap_create_channel(l2cap_handler, w->addr, PSM_HID_CONTROL, 0xffff, &w->ctrl_cid);
    gap_set_security_level(LEVEL_0);
    if (err != 0) {
        release(w);
        s_connecting = false;
        schedule_inquiry(1000);
    }
}

static void channel_opened(uint8_t *packet)
{
    uint16_t cid = l2cap_event_channel_opened_get_local_cid(packet);
    uint16_t psm = l2cap_event_channel_opened_get_psm(packet);
    bool incoming = l2cap_event_channel_opened_get_incoming(packet);
    bd_addr_t addr;
    l2cap_event_channel_opened_get_address(packet, addr);
    wiimote_t *w = by_cid(cid);
    if (!w)
        w = by_addr(addr);
    if (w && w->pairing && !incoming && psm == PSM_HID_CONTROL &&
        l2cap_event_channel_opened_get_status(packet) == L2CAP_CONNECTION_RESPONSE_RESULT_REFUSED_SECURITY) {
        // pairing refused: woken with 1 + 2, linked without (to search again next time)
        s_pairing = "ko";
        w->pairing = false;
        if (l2cap_create_channel(l2cap_handler, w->addr, PSM_HID_CONTROL, 0xffff, &w->ctrl_cid) == 0)
            return;
    }
    if (l2cap_event_channel_opened_get_status(packet) != 0) {
        ESP_LOGW(TAG, "HID channel 0x%02x of %s failed (0x%02x)", psm, bd_addr_to_str(addr),
                 l2cap_event_channel_opened_get_status(packet));
        if (w) {
            if (w->handle != HCI_CON_HANDLE_INVALID)
                gap_disconnect(w->handle);
            release(w);
        }
        if (!incoming)
            s_connecting = false;
        schedule_inquiry(500);
        return;
    }
    if (!w) {  // a channel nobody asked for
        l2cap_disconnect(cid);
        return;
    }
    w->handle = l2cap_event_channel_opened_get_handle(packet);
    if (psm == PSM_HID_CONTROL) {
        w->ctrl_cid = cid;
        // outgoing: the interrupt channel comes next (incoming: the Wii Remote opens it)
        if (!incoming &&
            l2cap_create_channel(l2cap_handler, w->addr, PSM_HID_INTERRUPT, 0xffff, &w->intr_cid) != 0) {
            gap_disconnect(w->handle);
        }
        return;
    }
    w->intr_cid = cid;
    w->ready = true;
    ESP_LOGI(TAG, "Wii Remote %s ready (slot %d)", bd_addr_to_str(w->addr), slot_of(w) + 1);
    announce(w);
    s_last_link = incoming ? "seule" : "rech";
    if (!incoming)
        s_connecting = false;
    if (s_inquiring && !want_search())
        gap_inquiry_stop();
    schedule_inquiry(200);
}

static void channel_closed(uint16_t cid)
{
    wiimote_t *w = by_cid(cid);
    if (!w)
        return;
    if (w->ctrl_cid == cid)
        w->ctrl_cid = 0;
    if (w->intr_cid == cid)
        w->intr_cid = 0;
    if (w->ctrl_cid || w->intr_cid) {  // one channel left: drop the whole link
        if (w->handle != HCI_CON_HANDLE_INVALID)
            gap_disconnect(w->handle);
        if (w->ready) {
            link_send(EB_WIIMOTE_OFF, slot_of(w), NULL, 0);
            w->ready = false;
        }
        return;
    }
    release(w);
    schedule_inquiry(200);
}

static void send_next(wiimote_t *w)
{
    if (!w->out_count || !w->intr_cid)
        return;
    uint8_t i = w->out_head;
    if (l2cap_send(w->intr_cid, w->out[i], w->out_len[i]) == 0) {
        w->out_head = (i + 1) % OUT_QUEUE;
        w->out_count--;
    }
    if (w->out_count)
        l2cap_request_can_send_now_event(w->intr_cid);
}

static void l2cap_handler(uint8_t type, uint16_t channel, uint8_t *packet, uint16_t size)
{
    if (type == L2CAP_DATA_PACKET) {
        wiimote_t *w = by_cid(channel);
        if (w && w->ready && channel == w->intr_cid && size <= EB_MAX_PAYLOAD) {
            int64_t now = esp_timer_get_time();
            if (s_bt_last && now - s_bt_last > s_bt_gap)
                s_bt_gap = now - s_bt_last;
            s_bt_last = now;
            s_bt_reports++;
            link_send(EB_REPORT, slot_of(w), packet, size);
        }
        return;
    }
    if (type != HCI_EVENT_PACKET)
        return;
    switch (hci_event_packet_get_type(packet)) {
    case L2CAP_EVENT_INCOMING_CONNECTION: {
        // a Wii Remote paired with SYNC wakes up and connects by itself
        bd_addr_t addr;
        l2cap_event_incoming_connection_get_address(packet, addr);
        uint16_t cid = l2cap_event_incoming_connection_get_local_cid(packet);
        wiimote_t *w = by_addr(addr);
        if (!w && s_scan)
            w = alloc(addr);
        if (w)
            l2cap_accept_connection(cid);
        else
            l2cap_decline_connection(cid);
        break;
    }
    case L2CAP_EVENT_CHANNEL_OPENED:
        channel_opened(packet);
        break;
    case L2CAP_EVENT_CHANNEL_CLOSED:
        channel_closed(l2cap_event_channel_closed_get_local_cid(packet));
        break;
    case L2CAP_EVENT_CAN_SEND_NOW: {
        wiimote_t *w = by_cid(l2cap_event_can_send_now_get_local_cid(packet));
        if (w)
            send_next(w);
        break;
    }
    }
}

static void hci_handler(uint8_t type, uint16_t channel, uint8_t *packet, uint16_t size)
{
    if (type != HCI_EVENT_PACKET)
        return;
    switch (hci_event_packet_get_type(packet)) {
    case HCI_EVENT_CONNECTION_REQUEST:
        s_calls++;
        s_call_pending = true;
        break;
    case HCI_EVENT_CONNECTION_COMPLETE:
        if (s_call_pending) {
            s_call_pending = false;
            s_call_status = hci_event_connection_complete_get_status(packet);
        }
        break;
    case BTSTACK_EVENT_STATE:
        if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) {
            bd_addr_t local;
            gap_local_bd_addr(local);
            ESP_LOGI(TAG, "Bluetooth up, address %s", bd_addr_to_str(local));
            start_inquiry();
        }
        break;
    case GAP_EVENT_INQUIRY_RESULT: {
        uint32_t cod = gap_event_inquiry_result_get_class_of_device(packet);
        bd_addr_t addr;
        gap_event_inquiry_result_get_bd_addr(packet, addr);
        if ((cod == COD_WIIMOTE || cod == COD_WIIMOTE_TR) && !by_addr(addr) && !s_have_candidate) {
            bd_addr_copy(s_candidate, addr);
            s_have_candidate = true;
            gap_inquiry_stop();
        }
        break;
    }
    case GAP_EVENT_INQUIRY_COMPLETE:
        s_inquiring = false;
        if (s_have_candidate && want_search())
            connect_candidate();
        else
            schedule_inquiry(100);
        break;
    case HCI_EVENT_PIN_CODE_REQUEST: {
        // pairing a Wii Remote woken with SYNC: the PIN is our address, byte-reversed (1 + 2
        // would take its own, but such a pairing isn't remembered by the Wii Remote: not tried)
        bd_addr_t addr, pin;
        hci_event_pin_code_request_get_bd_addr(packet, addr);
        gap_local_bd_addr(pin);
        uint8_t rev[6];
        for (int i = 0; i < 6; i++)
            rev[i] = pin[5 - i];
        gap_pin_code_response_binary(addr, rev, 6);
        break;
    }
    case HCI_EVENT_LINK_KEY_NOTIFICATION: {
        // BTstack keeps a key only when bonding was asked in Secure Simple Pairing, which Wii
        // Remotes don't do: kept here (NVS), for the Wii Remote to reconnect later
        bd_addr_t addr;
        reverse_bd_addr(&packet[2], addr);
        gap_store_link_key_for_bd_addr(addr, &packet[8], (link_key_type_t)packet[24]);
        s_pairing = "ok";
        ESP_LOGI(TAG, "Wii Remote %s paired (SYNC): it comes back at any button", bd_addr_to_str(addr));
        break;
    }
    }
}

// ---------------------------------------------------------------- Wolfy

static void handle_frame(const inbound_t *f)
{
    wiimote_t *w = f->slot < EB_SLOTS && s_wm[f->slot].used ? &s_wm[f->slot] : NULL;
    switch (f->type) {
    case EB_HELLO:  // (re)linked to Wolfy: tell it which Wii Remotes are there
        for (int i = 0; i < EB_SLOTS; i++)
            if (s_wm[i].ready)
                announce(&s_wm[i]);
        break;
    case EB_SCAN:
        s_scan = f->len && f->data[0];
        if (want_search())
            start_inquiry();
        else if (s_inquiring)
            gap_inquiry_stop();
        break;
    case EB_REPORT:
        if (!w || !w->ready || !f->len)
            break;
        if (w->out_count == OUT_QUEUE) {  // radio too slow: drop the oldest report
            w->out_head = (w->out_head + 1) % OUT_QUEUE;
            w->out_count--;
        }
        uint8_t i = (w->out_head + w->out_count) % OUT_QUEUE;
        memcpy(w->out[i], f->data, f->len);
        w->out_len[i] = f->len;
        if (++w->out_count == 1)
            l2cap_request_can_send_now_event(w->intr_cid);
        break;
    case EB_DROP:
        if (w && w->handle != HCI_CON_HANDLE_INVALID)
            gap_disconnect(w->handle);
        break;
    case EB_SETUP:
        s_setup_left = SETUP_ALIVE_MS;
        break;
    case EB_SEARCH:
        start_search();
        break;
    }
}

void wiimotes_stats(char *out, size_t size, uint32_t ms)
{
    // EB_MAX_PAYLOAD: 64 bytes
    char call[12] = "-";
    if (s_call_status >= 0)
        snprintf(call, sizeof(call), "%02x", (unsigned)s_call_status & 0xff);
    snprintf(out, size, "bt %lu/s, trou %lldms, wii %s, venue %s, app %s, appel %lu/%s",
             (unsigned long)(s_bt_reports * 1000 / (ms ? ms : 1)), s_bt_gap / 1000,
             s_scan ? "oui" : "non", s_last_link, s_pairing, (unsigned long)s_calls, call);
    s_bt_reports = 0;
    s_bt_gap = 0;
}

// ---------------------------------------------------------------- search button

static void tick(btstack_timer_source_t *ts)
{
    s_ticks++;
    if (button_pressed()) {
        s_button_held += TICK_MS;
        if (s_button_held == SETUP_HOLD_MS) {  // once per press, held longer = no repeat
            ESP_LOGI(TAG, "setup page");
            // up: this closes it (LED off now), else on until the Wi-Fi ESP32 says it is up
            s_setup_left = s_setup_left ? 0 : SETUP_BOOT_MS;
            setup_request();
        }
    } else {
        if (s_button_held >= BUTTON_HOLD_MS && s_button_held < SETUP_HOLD_MS)
            start_search();
        s_button_held = 0;
    }
    if (s_setup_left)
        s_setup_left = s_setup_left > TICK_MS ? s_setup_left - TICK_MS : 0;
    if (s_search_left) {
        s_search_left = s_search_left > TICK_MS ? s_search_left - TICK_MS : 0;
        if (!s_search_left) {
            ESP_LOGI(TAG, "search over");
            if (s_inquiring && !want_search())
                gap_inquiry_stop();
        }
    }
    bool led;
    if (s_button_held && s_button_held < SETUP_HOLD_MS)
        led = s_button_held % 1000 < 300;  // one blink per second held
    else if (s_setup_left)
        led = true;
    else
        led = want_search() && (s_ticks / 3) % 2;  // ~3 blinks per second
    set_led(led);
    btstack_run_loop_set_timer(ts, TICK_MS);
    btstack_run_loop_add_timer(ts);
}

void wiimotes_init(void)
{
    s_in = xQueueCreate(32, sizeof(inbound_t));
    s_in_cb.callback = drain_inbound;

    l2cap_init();
    gap_set_security_level(LEVEL_0);  // Wii Remotes in 1 + 2 mode don't authenticate
    gap_ssp_set_enable(0);            // they only know legacy PIN pairing
    gap_set_local_name("WolfyBar");
    gap_set_class_of_device(0x000104);  // shown as a computer
    gap_set_default_link_policy_settings(LM_LINK_POLICY_ENABLE_ROLE_SWITCH);
    gap_connectable_control(1);         // Wii Remotes paired with SYNC connect to us
    // a Wii Remote whose batteries are pulled is gone after 2 s, not 20 (when we are master:
    // found by the search), and can come back at once
    gap_set_link_supervision_timeout(3200);
    l2cap_register_service(l2cap_handler, PSM_HID_CONTROL, 0xffff, LEVEL_0);
    l2cap_register_service(l2cap_handler, PSM_HID_INTERRUPT, 0xffff, LEVEL_0);

#ifndef WIIMOTES_REMOTE_BUTTON
    gpio_reset_pin(BUTTON);
    gpio_set_direction(BUTTON, GPIO_MODE_INPUT);
    gpio_set_pull_mode(BUTTON, GPIO_PULLDOWN_ONLY);
    gpio_reset_pin(SEARCH_LED);
    gpio_set_direction(SEARCH_LED, GPIO_MODE_OUTPUT);
    gpio_set_level(SEARCH_LED, 0);
#endif
    btstack_run_loop_set_timer_handler(&s_tick, tick);
    btstack_run_loop_set_timer(&s_tick, TICK_MS);
    btstack_run_loop_add_timer(&s_tick);

    s_hci_cb.callback = hci_handler;
    hci_add_event_handler(&s_hci_cb);
    hci_power_control(HCI_POWER_ON);
}
