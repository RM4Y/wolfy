#pragma once
#include <stdbool.h>

typedef struct {
    char ssid[33];
    char password[65];
    char url[201];  // Wolfy's WebSocket: wss://wolfy.rm4.fr/api/espbar/ws or ws://<lan ip>:8420/...
    bool tls;       // parsed from url
    char host[128];
    int port;
    char path[128];
    char token[65];
} espbar_config_t;

// Reads the "espbar" partition written by Wolfy: "EB01" then a NUL-terminated JSON object.
bool config_load(espbar_config_t *cfg);
