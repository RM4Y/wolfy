// Setup page: an open access point "EspBar-XXXX" whose page (captive portal, http://192.168.4.1)
// sets the Wi-Fi network and Wolfy's address. Opened by holding the button 10 s (or without
// any configuration), instead of the link to Wolfy.
#pragma once
#include <stdbool.h>

#include "config.h"

// This boot is for the setup page (asked by setup_reboot(true)); clears the request.
bool setup_requested(void);

// Restarts into the setup page, or normally.
void setup_reboot(bool setup);

// Runs the page with <cfg> as it is (possibly empty) until saved, closed or SETUP_IDLE_MS
// without a visit; then restarts normally. Never returns.
void setup_run(const espbar_config_t *cfg);

// Implemented by the program: called every 100 ms while the page is up (its LED, its button).
void setup_poll(void);
