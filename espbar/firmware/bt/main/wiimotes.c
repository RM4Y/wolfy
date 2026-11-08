#include "wiimotes.h"

#include <string.h>

#include <stdint.h>
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
// Speaker data (0x18): the Wii Remote plays it as it comes, and it comes in bursts (Dolphin sends
// a video frame's worth at once, then Wi-Fi and TCP add theirs): it crackled. Held here ~60 ms,
// then given at the pace it arrives at on average.
#define SPK_QUEUE 24
#define SPK_LEN 23                // a2 18 + length/rumble + 20 bytes of ADPCM
#define SPK_PREBUF_US 60000
#define SPK_SILENCE_US 100000     // a longer gap: the next report starts a new sound
#define SPK_STEP_US 13333         // first guess: 75 reports/s (3000 Hz, 4-bit ADPCM)
// Sniff mode, as a Wii sets it: the Wii Remote then runs at 200 Hz. At 100 Hz (active mode) a
// Wii Remote before the -TR misses speaker data and its decoder loses the game's encoder: the
// crackle (bugs.dolphin-emu.org/issues/5977). 8 slots of 0.625 ms = 5 ms, attempt 1, timeout 0.
#define SNIFF_INTERVAL 8
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
    uint8_t spk[SPK_QUEUE][SPK_LEN];  // speaker reports, given to out[] at a steady pace
    uint8_t spk_len[SPK_QUEUE];
    uint8_t spk_head, spk_count;
    bool spk_playing;
    int64_t spk_due;    // us: next one goes out then (playing)
    int64_t spk_since;  // us: the oldest waiting one came then (not playing yet)
    int64_t spk_last;   // us: last one came then
    int32_t spk_step;   // us between two of them, on average
    uint8_t rumble;     // rumble bit of the game's last output report
    bool master;        // we are master of its link (we poll it: steady speaker data)
    bool sniff;         // its link is in sniff mode (SNIFF_INTERVAL)
    int64_t spk_sent;   // us: its last speaker report went on the radio then
    int64_t spk_gap;    // us: longest gap between two of them within a sound (stats)
    int64_t out_since;  // us: the first waiting output report was queued then
    int64_t out_wait;   // us: longest wait of one for the radio (stats)
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
static btstack_timer_source_t s_spk_timer;
static btstack_packet_callback_registration_t s_hci_cb;

// reports from the Wii Remotes since the last wiimotes_stats(), longest wait between two (us)
static uint32_t s_bt_reports;
// shown in the stats (no log here: UART0 is the link to the Wi-Fi ESP32)
static const char *s_last_link = "-";  // how the last Wii Remote came (search or by itself)
static const char *s_pairing = "-";    // the last pairing (ok / ko)
static int64_t s_bt_last, s_bt_gap;
// speaker data, in the stats while it comes (its crackle): received, lost here (and per Wii
// Remote: longest gap on the radio, longest wait of an output report for it)
static uint32_t s_spk_in;
static volatile uint32_t s_spk_lost;

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
    if (xQueueSend(s_in, &f, 0) != pdTRUE) {
        s_spk_lost += type == EB_REPORT && f.len > 1 && f.data[1] == 0x18;
        return;  // full: an output report is lost, the game sends more
    }
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
    // a Wii Remote that called us is master of the link: we could only send when it polls us
    // (two of them: two piconets to share our time), and its speaker data came in bursts.
    // A Wii takes the master role, as we ask at accept (wiimotes_init): asked again if it didn't take.
    // Then sniff mode (once the role is settled: a role switch needs active mode).
    w->master = gap_get_role(w->handle) == HCI_ROLE_MASTER;
    if (w->master)
        gap_sniff_mode_enter(w->handle, SNIFF_INTERVAL, SNIFF_INTERVAL, 1, 0);
    else
        gap_request_role(w->addr, HCI_ROLE_MASTER);
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
        int64_t now = esp_timer_get_time();
        if (now - w->out_since > w->out_wait)
            w->out_wait = now - w->out_since;
        w->out_since = now;  // the next one waits from now (or from its queuing, later)
        if (w->out[i][1] == 0x18) {
            if (now - w->spk_sent < SPK_SILENCE_US && now - w->spk_sent > w->spk_gap)
                w->spk_gap = now - w->spk_sent;
            w->spk_sent = now;
        }
        w->out_head = (i + 1) % OUT_QUEUE;
        w->out_count--;
    }
    if (w->out_count)
        l2cap_request_can_send_now_event(w->intr_cid);
}

static void out_push(wiimote_t *w, const uint8_t *data, uint8_t len)
{
    if (w->out_count == OUT_QUEUE) {  // radio too slow: drop the oldest report
        s_spk_lost += w->out[w->out_head][1] == 0x18;
        w->out_head = (w->out_head + 1) % OUT_QUEUE;
        w->out_count--;
    }
    uint8_t i = (w->out_head + w->out_count) % OUT_QUEUE;
    memcpy(w->out[i], data, len);
    w->out_len[i] = len;
    if (++w->out_count == 1) {
        w->out_since = esp_timer_get_time();
        l2cap_request_can_send_now_event(w->intr_cid);
    }
}

// ---------------------------------------------------------------- speaker pacing

static void spk_release(wiimote_t *w)
{
    uint8_t *r = w->spk[w->spk_head];
    r[2] = (r[2] & ~1) | w->rumble;  // its rumble bit is ~60 ms old: the game's current one
    out_push(w, r, w->spk_len[w->spk_head]);
    w->spk_head = (w->spk_head + 1) % SPK_QUEUE;
    w->spk_count--;
}

// Before a speaker enable / mute: the sound held here goes first, in order (what fits).
static void spk_flush(wiimote_t *w)
{
    while (w->spk_count && w->out_count < OUT_QUEUE)
        spk_release(w);
    w->spk_count = 0;
    w->spk_playing = false;
}

static void spk_schedule(void);

static void spk_tick(btstack_timer_source_t *ts)
{
    int64_t now = esp_timer_get_time();
    for (int i = 0; i < EB_SLOTS; i++) {
        wiimote_t *w = &s_wm[i];
        if (!w->used || !w->spk_count)
            continue;
        if (!w->spk_playing && (w->spk_count * w->spk_step >= SPK_PREBUF_US || now - w->spk_since >= SPK_PREBUF_US)) {
            w->spk_playing = true;
            w->spk_due = now;
        }
        if (!w->spk_playing)
            continue;
        if (w->spk_due < now - SPK_PREBUF_US)  // the radio held us up: no burst to catch up
            w->spk_due = now;
        while (w->spk_count && w->spk_due <= now) {
            // more than twice the margin held (it came faster than it goes): a little faster
            int32_t step = w->spk_count * w->spk_step > 2 * SPK_PREBUF_US ? w->spk_step - w->spk_step / 8 : w->spk_step;
            spk_release(w);
            w->spk_due += step;
        }
        if (!w->spk_count)
            w->spk_playing = false;  // ran dry (end of the sound, or a hole): wait for a margin again
    }
    spk_schedule();
}

static void spk_schedule(void)
{
    int64_t wake = INT64_MAX;
    for (int i = 0; i < EB_SLOTS; i++) {
        wiimote_t *w = &s_wm[i];
        if (!w->used || !w->spk_count)
            continue;
        int64_t t = w->spk_playing ? w->spk_due : w->spk_since + SPK_PREBUF_US;
        if (!w->spk_playing && w->spk_count * w->spk_step >= SPK_PREBUF_US)
            t = 0;
        if (t < wake)
            wake = t;
    }
    btstack_run_loop_remove_timer(&s_spk_timer);
    if (wake == INT64_MAX)
        return;
    int64_t us = wake - esp_timer_get_time();
    btstack_run_loop_set_timer_handler(&s_spk_timer, spk_tick);
    btstack_run_loop_set_timer(&s_spk_timer, us > 1000 ? (uint32_t)((us + 999) / 1000) : 1);
    btstack_run_loop_add_timer(&s_spk_timer);
}

static void spk_push(wiimote_t *w, const uint8_t *data, uint8_t len)
{
    int64_t now = esp_timer_get_time();
    int64_t dt = now - w->spk_last;
    if (!w->spk_step)
        w->spk_step = SPK_STEP_US;
    if (w->spk_last && dt < SPK_SILENCE_US)
        w->spk_step += (int32_t)(dt - w->spk_step) / 16;
    w->spk_last = now;
    s_spk_in++;
    if (w->spk_count == SPK_QUEUE) {  // can't happen at the pace above: drop the oldest
        s_spk_lost++;
        w->spk_head = (w->spk_head + 1) % SPK_QUEUE;
        w->spk_count--;
    }
    if (!w->spk_count && !w->spk_playing)
        w->spk_since = now;
    uint8_t i = (w->spk_head + w->spk_count) % SPK_QUEUE;
    memcpy(w->spk[i], data, len);
    w->spk_len[i] = len;
    w->spk_count++;
    spk_schedule();
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
    case HCI_EVENT_MODE_CHANGE: {
        hci_con_handle_t handle = hci_event_mode_change_get_handle(packet);
        for (int i = 0; i < EB_SLOTS; i++)
            if (s_wm[i].used && s_wm[i].handle == handle) {
                s_wm[i].sniff = hci_event_mode_change_get_mode(packet) == 2;  // 0 active, 1 hold, 2 sniff
                ESP_LOGI(TAG, "Wii Remote %s: mode %u, interval %u (status 0x%02x)", bd_addr_to_str(s_wm[i].addr),
                         hci_event_mode_change_get_mode(packet), hci_event_mode_change_get_interval(packet),
                         hci_event_mode_change_get_status(packet));
            }
        break;
    }
    case HCI_EVENT_ROLE_CHANGE: {
        bd_addr_t addr;
        hci_event_role_change_get_bd_addr(packet, addr);
        wiimote_t *w = by_addr(addr);
        if (w && hci_event_role_change_get_status(packet) == 0)
            w->master = hci_event_role_change_get_role(packet) == HCI_ROLE_MASTER;
        if (w && w->ready)  // asked in channel_opened: sniff mode now, master or not
            gap_sniff_mode_enter(w->handle, SNIFF_INTERVAL, SNIFF_INTERVAL, 1, 0);
        ESP_LOGI(TAG, "Wii Remote %s: we are %s (status 0x%02x)", bd_addr_to_str(addr),
                 hci_event_role_change_get_role(packet) == HCI_ROLE_MASTER ? "master" : "slave",
                 hci_event_role_change_get_status(packet));
        break;
    }
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
        if (f->len >= 3 && f->data[0] == 0xa2) {  // output report: a2 + id + rumble bit, ...
            w->rumble = f->data[2] & 1;
            if (f->data[1] == 0x18 && f->len <= SPK_LEN) {
                spk_push(w, f->data, f->len);
                break;
            }
            if (f->data[1] == 0x14 || f->data[1] == 0x19)  // speaker on / off, mute
                spk_flush(w);
        }
        out_push(w, f->data, f->len);
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
    int ready = 0, master = 0, sniff = 0;
    for (int i = 0; i < EB_SLOTS; i++)
        if (s_wm[i].ready) {
            ready++;
            master += s_wm[i].master;
            sniff += s_wm[i].sniff;
        }
    unsigned long rate = s_bt_reports * 1000 / (ms ? ms : 1);
    if (s_spk_in) {  // sound: its figures in place of the pairing ones, "max" and "att" per Wii Remote
        char gaps[24] = "", peaks[24] = "";
        for (int i = 0; i < EB_SLOTS; i++)
            if (s_wm[i].ready) {
                snprintf(gaps + strlen(gaps), sizeof(gaps) - strlen(gaps), "%s%d", *gaps ? "/" : "",
                         (int)(s_wm[i].spk_gap / 1000));
                snprintf(peaks + strlen(peaks), sizeof(peaks) - strlen(peaks), "%s%d", *peaks ? "/" : "",
                         (int)(s_wm[i].out_wait / 1000));
            }
        snprintf(out, size, "bt %lu/s, maître %d/%d, sniff %d, perte %lu, max %sms att %sms", rate, master,
                 ready, sniff, (unsigned long)s_spk_lost, gaps, peaks);
    } else
        snprintf(out, size, "bt %lu/s, trou %lldms, wii %s, venue %s, app %s, maître %d/%d", rate,
                 s_bt_gap / 1000, s_scan ? "oui" : "non", s_last_link, s_pairing, master, ready);
    s_spk_in = s_spk_lost = 0;
    for (int i = 0; i < EB_SLOTS; i++) {
        s_wm[i].spk_gap = 0;
        s_wm[i].out_wait = 0;
    }
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
    gap_set_default_link_policy_settings(LM_LINK_POLICY_ENABLE_ROLE_SWITCH | LM_LINK_POLICY_ENABLE_SNIFF_MODE);
    hci_set_master_slave_policy(0);     // a Wii Remote calling us: we become master (channel_opened)
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
