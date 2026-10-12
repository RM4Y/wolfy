#include "setup.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#include "esp_attr.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

#define SETUP_IDLE_MS (10 * 60 * 1000)  // without a visit: back to the saved settings
#define SETUP_MAGIC 0x5e7a9b01
#define SCAN_MAX 20
#define PAGE_URL "http://192.168.4.1/"

static const char *TAG = "setup";
RTC_NOINIT_ATTR static uint32_t s_boot_setup;  // kept across esp_restart()
static espbar_config_t s_cfg;
static wifi_ap_record_t s_aps[SCAN_MAX];
static uint16_t s_ap_count;
static volatile int64_t s_last_visit;
static volatile bool s_saved;

bool setup_requested(void)
{
    bool asked = s_boot_setup == SETUP_MAGIC;
    s_boot_setup = 0;
    return asked;
}

void setup_reboot(bool setup)
{
    s_boot_setup = setup ? SETUP_MAGIC : 0;
    esp_restart();
}

// ---------------------------------------------------------------- Wi-Fi

static void scan(void)
{
    wifi_scan_config_t sc = {.show_hidden = false};
    s_ap_count = 0;
    if (esp_wifi_scan_start(&sc, true) != ESP_OK)
        return;
    uint16_t n = SCAN_MAX;
    if (esp_wifi_scan_get_ap_records(&n, s_aps) == ESP_OK)
        s_ap_count = n;
    // strongest first, each network once (several access points may share a name)
    for (int i = 0; i < s_ap_count; i++)
        for (int j = i + 1; j < s_ap_count; j++)
            if (s_aps[j].rssi > s_aps[i].rssi) {
                wifi_ap_record_t t = s_aps[i];
                s_aps[i] = s_aps[j];
                s_aps[j] = t;
            }
    int kept = 0;
    for (int i = 0; i < s_ap_count; i++) {
        bool seen = !s_aps[i].ssid[0];
        for (int j = 0; j < kept && !seen; j++)
            seen = strcmp((char *)s_aps[j].ssid, (char *)s_aps[i].ssid) == 0;
        if (!seen)
            s_aps[kept++] = s_aps[i];
    }
    s_ap_count = kept;
}

static void wifi_ap_start(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();  // scans
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    wifi_config_t wc = {.ap = {.channel = 1, .authmode = WIFI_AUTH_OPEN, .max_connection = 4}};
    wc.ap.ssid_len = snprintf((char *)wc.ap.ssid, sizeof(wc.ap.ssid), "WolfyBar-%02X%02X", mac[4], mac[5]);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "access point %s, page " PAGE_URL, wc.ap.ssid);
}

// ---------------------------------------------------------------- DNS: every name is us
// (phones then open the page by themselves, as on a hotel Wi-Fi)

static void dns_task(void *arg)
{
    int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(53), .sin_addr.s_addr = INADDR_ANY};
    if (fd < 0 || bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "no DNS server");
        vTaskDelete(NULL);
    }
    uint8_t buf[512];
    for (;;) {
        struct sockaddr_in from;
        socklen_t from_len = sizeof(from);
        int n = recvfrom(fd, buf, sizeof(buf) - 16, 0, (struct sockaddr *)&from, &from_len);
        if (n < 12 || (buf[2] & 0x80) || !(buf[4] << 8 | buf[5]))  // not a query
            continue;
        size_t q = 12;  // first question: name, type, class
        while (q < (size_t)n && buf[q])
            q += buf[q] + 1;
        if (q + 5 > (size_t)n)
            continue;
        bool type_a = buf[q + 1] == 0 && buf[q + 2] == 1;
        size_t len = q + 5;
        buf[2] = 0x81;  // response, recursion desired
        buf[3] = 0x80;  // recursion available, no error
        buf[4] = 0, buf[5] = 1;                      // 1 question
        buf[6] = 0, buf[7] = type_a;                 // answer: A only
        buf[8] = buf[9] = buf[10] = buf[11] = 0;
        if (type_a) {
            const uint8_t answer[] = {0xc0, 12, 0, 1, 0, 1, 0, 0, 0, 60, 0, 4, 192, 168, 4, 1};
            memcpy(buf + len, answer, sizeof(answer));
            len += sizeof(answer);
        }
        sendto(fd, buf, len, 0, (struct sockaddr *)&from, from_len);
    }
}

// ---------------------------------------------------------------- page

static void send_text(httpd_req_t *req, const char *text) { httpd_resp_sendstr_chunk(req, text); }

static void send_escaped(httpd_req_t *req, const char *text)
{
    char buf[128];
    size_t n = 0;
    for (; *text; text++) {
        const char *rep = *text == '<' ? "&lt;" : *text == '>' ? "&gt;" : *text == '&' ? "&amp;"
                        : *text == '"' ? "&quot;" : *text == '\'' ? "&#39;" : NULL;
        size_t len = rep ? strlen(rep) : 1;
        if (n + len >= sizeof(buf)) {
            httpd_resp_send_chunk(req, buf, n);
            n = 0;
        }
        memcpy(buf + n, rep ? rep : text, len);
        n += len;
    }
    if (n)
        httpd_resp_send_chunk(req, buf, n);
}

// The page looks like Wolfy (glass on an aurora, Wolfy violet); system fonts: the phone has no
// Internet on this network
#define PAGE_HEAD                                                                                    \
    "<!doctype html><html lang=fr><meta charset=utf-8>"                                              \
    "<meta name=viewport content='width=device-width,initial-scale=1'>"                              \
    "<meta name=theme-color content=#07060f><title>WolfyBar</title><style>"                          \
    "*{box-sizing:border-box}"                                                                       \
    "body{margin:0;min-height:100vh;font:15px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;"   \
    "color:#eceef4;background-color:#07060f;background-image:"                                       \
    "radial-gradient(520px 420px at 10% -10%,rgba(124,92,255,.55),transparent 65%),"                 \
    "radial-gradient(420px 380px at 110% 10%,rgba(41,178,230,.3),transparent 65%),"                  \
    "radial-gradient(600px 400px at 50% 115%,rgba(230,60,140,.25),transparent 65%);"                 \
    "background-repeat:no-repeat;background-attachment:fixed;padding:20px 16px 32px}"                \
    ".w{max-width:440px;margin:0 auto}"                                                              \
    ".c{background:rgba(255,255,255,.045) linear-gradient(160deg,rgba(255,255,255,.06),transparent 40%);" \
    "border:1px solid rgba(255,255,255,.11);border-radius:16px;padding:20px;"                        \
    "box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 10px 30px -12px rgba(0,0,0,.6);"               \
    "-webkit-backdrop-filter:blur(18px) saturate(150%);backdrop-filter:blur(18px) saturate(150%)}"

#define LOCK_ICON                                                                                    \
    "<svg viewBox=\"0 0 24 24\" fill=none stroke=currentColor stroke-width=2>"                       \
    "<rect x=5 y=11 width=14 height=10 rx=2 /><path d=\"M8 11V7a4 4 0 0 1 8 0v4\"/></svg>"

static void send_page(httpd_req_t *req, const char *error)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    send_text(req, PAGE_HEAD
        ".h{display:flex;align-items:center;gap:12px;margin:4px 4px 18px}"
        ".h svg{width:40px;height:40px;border-radius:11px;"
        "box-shadow:0 0 0 1px rgba(180,159,255,.35),0 8px 28px -6px rgba(124,92,255,.65)}"
        ".h b{display:block;font-size:20px;letter-spacing:-.01em}.h small{color:#9aa1b2;font-size:13px}"
        "label{display:block;font-weight:600;margin:18px 0 8px}label:first-child{margin-top:0}"
        "input{width:100%;height:44px;padding:0 12px;font:inherit;font-size:16px;color:#eceef4;"
        "background:rgba(255,255,255,.045);border:1px solid #5e667c;border-radius:10px;outline:0}"
        "input:focus{border-color:#6d50f0;box-shadow:0 0 0 3px rgba(124,98,255,.16),0 0 20px -6px rgba(124,92,255,.55)}"
        "input::placeholder{color:#7d8498}"
        ".n{display:flex;align-items:center;gap:10px;width:100%;margin-top:6px;padding:11px 12px;font:inherit;"
        "color:#eceef4;text-align:left;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.11);"
        "border-radius:10px;cursor:pointer}"
        ".n i{flex:1;font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".n.on{border-color:#6d50f0;background:rgba(124,98,255,.16);"
        "box-shadow:0 0 0 1px #6d50f0 inset,0 0 28px -8px rgba(124,92,255,.55)}"
        ".n svg{width:15px;height:15px;color:#9aa1b2;flex:none}"
        ".s{display:inline-flex;align-items:flex-end;gap:2px;height:14px}"
        ".s u{width:3px;border-radius:1px;background:rgba(255,255,255,.18)}"
        ".s u:nth-child(1){height:25%}.s u:nth-child(2){height:50%}.s u:nth-child(3){height:75%}"
        ".s u:nth-child(4){height:100%}"
        ".s1 u:nth-child(-n+1),.s2 u:nth-child(-n+2),.s3 u:nth-child(-n+3),.s4 u{background:#4ade9a}"
        ".m{color:#9aa1b2;font-size:13px;margin:8px 0 0}a{color:#a993ff;font-weight:600;text-decoration:none}"
        "code{font:12.5px ui-monospace,Menlo,monospace;color:#eceef4}"
        "button.b{width:100%;height:46px;margin-top:22px;font:600 16px system-ui,sans-serif;color:#fff;border:0;"
        "border-radius:10px;background:#6d50f0 linear-gradient(180deg,rgba(255,255,255,.18),transparent 55%);"
        "box-shadow:0 0 0 1px rgba(180,159,255,.35),0 8px 28px -6px rgba(124,92,255,.65),"
        "inset 0 1px 0 rgba(255,255,255,.25);cursor:pointer}"
        ".e{display:flex;gap:10px;margin:0 0 16px;padding:12px 14px;border-radius:10px;"
        "background:rgba(255,122,122,.12);color:#eceef4}"
        ".e:before{content:'!';flex:none;width:20px;height:20px;border-radius:50%;background:#ff7a7a;"
        "color:#0b0d12;font-weight:700;text-align:center;line-height:20px}"
        ".f{color:#7d8498;font-size:12.5px;text-align:center;margin:16px 8px 0}"
        "</style><div class=w><div class=h>"
        "<svg viewBox=\"0 0 64 64\"><rect width=64 height=64 fill=#6d50f0 />"
        "<path d=\"M14 18l8 6 10-8 10 8 8-6-4 22-14 10-14-10z\" fill=#fff />"
        "<circle cx=26 cy=32 r=2.5 fill=#6d50f0 /><circle cx=38 cy=32 r=2.5 fill=#6d50f0 /></svg>"
        "<div><b>WolfyBar</b><small>Réglage du Wi-Fi</small></div></div>");
    if (error) {
        send_text(req, "<p class=e>");
        send_text(req, error);
        send_text(req, "</p>");
    }
    if (!s_cfg.token[0])
        send_text(req, "<p class=e>Jeton de Wolfy absent : injecte d'abord la WolfyBar depuis Wolfy "
                       "(Wii › WolfyBar), puis reviens ici pour changer de Wi-Fi.</p>");
    send_text(req, "<form class=c method=post action=/save><label>Réseau Wi-Fi</label>"
                   "<input id=s name=ssid required maxlength=32 autocomplete=off value=\"");
    send_escaped(req, s_cfg.ssid);
    send_text(req, "\">");
    for (int i = 0; i < s_ap_count; i++) {
        const char *ssid = (const char *)s_aps[i].ssid;
        int rssi = s_aps[i].rssi;
        int bars = rssi >= -55 ? 4 : rssi >= -65 ? 3 : rssi >= -75 ? 2 : 1;
        char sig[96];
        snprintf(sig, sizeof(sig), "<span class=\"s s%d\" title=\"%d dBm\"><u></u><u></u><u></u><u></u></span>",
                 bars, rssi);
        send_text(req, strcmp(ssid, s_cfg.ssid) ? "<button type=button class=n data-s=\""
                                                 : "<button type=button class=\"n on\" data-s=\"");
        send_escaped(req, ssid);
        send_text(req, "\"><i>");
        send_escaped(req, ssid);
        send_text(req, "</i>");
        if (s_aps[i].authmode != WIFI_AUTH_OPEN)
            send_text(req, LOCK_ICON);
        send_text(req, sig);
        send_text(req, "</button>");
    }
    send_text(req, "<p class=m><a href='/?scan=1'>Rechercher les réseaux</a></p>"
                   "<label>Mot de passe</label><input id=p name=password type=password maxlength=64 "
                   "placeholder='Vide : inchangé ou réseau ouvert'>"
                   "<label>Adresse de Wolfy</label><input name=url required maxlength=200 value=\"");
    send_escaped(req, s_cfg.url);
    send_text(req, "\"><p class=m><code>wss://wolfy.rm4.fr/api/espbar/ws</code>, ou "
                   "<code>ws://&lt;IP du serveur&gt;:8420/api/espbar/ws</code> sur le réseau local</p>"
                   "<button class=b>Enregistrer et redémarrer</button></form>"
                   "<p class=f>Sans enregistrement, la WolfyBar repart avec ses réglages au bout de 10 min, "
                   "ou quand on maintient de nouveau son bouton 10 s.</p></div>"
                   "<script>document.querySelectorAll('.n').forEach(b=>b.onclick=()=>{"
                   "document.querySelectorAll('.n').forEach(x=>x.classList.remove('on'));"
                   "b.classList.add('on');s.value=b.dataset.s;p.focus()})</script>");
    httpd_resp_send_chunk(req, NULL, 0);
}

static esp_err_t page_get(httpd_req_t *req)
{
    s_last_visit = esp_timer_get_time();
    char query[16];
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK && strstr(query, "scan"))
        scan();
    send_page(req, NULL);
    return ESP_OK;
}

static void url_decode(char *dst, size_t size, const char *src)
{
    size_t n = 0;
    while (*src && n + 1 < size) {
        if (*src == '+') {
            dst[n++] = ' ';
            src++;
        } else if (*src == '%' && isxdigit((unsigned char)src[1]) && isxdigit((unsigned char)src[2])) {
            char hex[3] = {src[1], src[2], 0};
            dst[n++] = strtol(hex, NULL, 16);
            src += 3;
        } else {
            dst[n++] = *src++;
        }
    }
    dst[n] = 0;
}

static void form_value(const char *body, const char *key, char *out, size_t size)
{
    char raw[3 * 200 + 1];
    if (httpd_query_key_value(body, key, raw, sizeof(raw)) != ESP_OK)
        raw[0] = 0;
    url_decode(out, size, raw);
}

static esp_err_t save_post(httpd_req_t *req)
{
    s_last_visit = esp_timer_get_time();
    static char body[1024];
    if (req->content_len >= sizeof(body)) {
        send_page(req, "Formulaire trop long.");
        return ESP_OK;
    }
    size_t len = 0;
    while (len < req->content_len) {
        int r = httpd_req_recv(req, body + len, req->content_len - len);
        if (r <= 0)
            return ESP_FAIL;
        len += r;
    }
    body[len] = 0;

    espbar_config_t cfg = s_cfg;
    form_value(body, "ssid", cfg.ssid, sizeof(cfg.ssid));
    form_value(body, "password", cfg.password, sizeof(cfg.password));
    form_value(body, "url", cfg.url, sizeof(cfg.url));
    if (!cfg.password[0] && strcmp(cfg.ssid, s_cfg.ssid) == 0)
        strlcpy(cfg.password, s_cfg.password, sizeof(cfg.password));  // same network: unchanged
    if (!cfg.ssid[0]) {
        send_page(req, "Choisis un réseau Wi-Fi.");
        return ESP_OK;
    }
    if (!config_save(&cfg)) {
        // shown again as typed, so it can be fixed
        strlcpy(s_cfg.url, cfg.url, sizeof(s_cfg.url));
        send_page(req, "Adresse de Wolfy invalide (ws://… ou wss://…), ou écriture ratée.");
        return ESP_OK;
    }
    s_cfg = cfg;
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    send_text(req, PAGE_HEAD
                   ".k{display:grid;place-items:center;width:48px;height:48px;margin:6px auto 14px;"
                   "border-radius:50%;background:rgba(74,222,154,.12);color:#4ade9a;"
                   "box-shadow:0 0 0 1px rgba(74,222,154,.3),0 0 28px -6px #4ade9a}"
                   ".k svg{width:24px;height:24px}"
                   "h1{margin:0 0 6px;font-size:20px;text-align:center}"
                   "p{margin:0;color:#9aa1b2;text-align:center}b{color:#eceef4}"
                   "</style><div class=w><div class=c><div class=k>"
                   "<svg viewBox=\"0 0 24 24\" fill=none stroke=currentColor stroke-width=2.2 "
                   "stroke-linecap=round stroke-linejoin=round><path d=\"m5 12.5 4.5 4.5L19 7.5\"/></svg></div>"
                   "<h1>Enregistré</h1><p>La WolfyBar redémarre et se connecte à <b>« ");
    send_escaped(req, cfg.ssid);
    send_text(req, " »</b>. Tu peux quitter ce réseau.</p></div></div>");
    httpd_resp_send_chunk(req, NULL, 0);
    s_saved = true;
    return ESP_OK;
}

// anything else (phones checking for Internet: /generate_204, /hotspot-detect.html...): the page
static esp_err_t redirect(httpd_req_t *req, httpd_err_code_t err)
{
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", PAGE_URL);
    httpd_resp_send(req, NULL, 0);
    return ESP_OK;
}

static void http_start(void)
{
    httpd_handle_t server;
    httpd_config_t hc = HTTPD_DEFAULT_CONFIG();
    hc.stack_size = 8192;
    hc.lru_purge_enable = true;  // phones open many connections
    ESP_ERROR_CHECK(httpd_start(&server, &hc));
    const httpd_uri_t page = {.uri = "/", .method = HTTP_GET, .handler = page_get};
    const httpd_uri_t save = {.uri = "/save", .method = HTTP_POST, .handler = save_post};
    httpd_register_uri_handler(server, &page);
    httpd_register_uri_handler(server, &save);
    httpd_register_err_handler(server, HTTPD_404_NOT_FOUND, redirect);
}

// ---------------------------------------------------------------- task

void setup_run(const espbar_config_t *cfg)
{
    s_cfg = *cfg;
    wifi_ap_start();
    scan();
    xTaskCreate(dns_task, "dns", 3072, NULL, 5, NULL);
    http_start();
    s_last_visit = esp_timer_get_time();
    for (;;) {
        setup_poll();
        vTaskDelay(pdMS_TO_TICKS(100));
        if (s_saved) {
            vTaskDelay(pdMS_TO_TICKS(1000));  // the answer reaches the phone
            setup_reboot(false);
        }
        if (esp_timer_get_time() - s_last_visit > SETUP_IDLE_MS * 1000LL) {
            ESP_LOGI(TAG, "no visit: back to the saved settings");
            setup_reboot(false);
        }
    }
}
