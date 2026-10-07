#include "config.h"

#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_log.h"
#include "esp_partition.h"

static const char *TAG = "config";
#define CONFIG_SUBTYPE 0x40
#define CONFIG_SIZE 0x1000

static void copy(char *dst, size_t size, const cJSON *obj, const char *key)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    dst[0] = 0;
    if (cJSON_IsString(v))
        strlcpy(dst, v->valuestring, size);
}

// ws[s]://host[:port][/path]
static bool parse_url(espbar_config_t *cfg)
{
    const char *p = cfg->url;
    if (strncmp(p, "wss://", 6) == 0) {
        cfg->tls = true;
        p += 6;
    } else if (strncmp(p, "ws://", 5) == 0) {
        p += 5;
    } else {
        return false;
    }
    size_t host_len = strcspn(p, ":/");
    if (!host_len || host_len >= sizeof(cfg->host))
        return false;
    memcpy(cfg->host, p, host_len);
    cfg->host[host_len] = 0;
    p += host_len;
    cfg->port = cfg->tls ? 443 : 80;
    if (*p == ':') {
        cfg->port = atoi(p + 1);
        p += strcspn(p, "/");
    }
    strlcpy(cfg->path, *p ? p : "/", sizeof(cfg->path));
    return cfg->port > 0;
}

bool config_load(espbar_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    const esp_partition_t *part =
        esp_partition_find_first(ESP_PARTITION_TYPE_DATA, CONFIG_SUBTYPE, "espbar");
    if (!part) {
        ESP_LOGE(TAG, "no espbar partition");
        return false;
    }
    static char buf[CONFIG_SIZE];
    if (esp_partition_read(part, 0, buf, sizeof(buf)) != ESP_OK || memcmp(buf, "EB01", 4) != 0) {
        ESP_LOGE(TAG, "no configuration: inject the EspBar from Wolfy");
        return false;
    }
    buf[sizeof(buf) - 1] = 0;
    cJSON *json = cJSON_Parse(buf + 4);
    if (!json) {
        ESP_LOGE(TAG, "invalid configuration");
        return false;
    }
    copy(cfg->ssid, sizeof(cfg->ssid), json, "ssid");
    copy(cfg->password, sizeof(cfg->password), json, "password");
    copy(cfg->url, sizeof(cfg->url), json, "url");
    copy(cfg->token, sizeof(cfg->token), json, "token");
    cJSON_Delete(json);
    if (!parse_url(cfg)) {
        ESP_LOGE(TAG, "invalid Wolfy address: %s", cfg->url);
        return false;
    }
    ESP_LOGI(TAG, "Wi-Fi \"%s\", Wolfy %s", cfg->ssid, cfg->url);
    return cfg->ssid[0] != 0;
}
