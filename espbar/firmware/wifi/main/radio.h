// The Bluetooth ESP32, behind UART2 (also implements the radio_* of link.h).
#pragma once

// Checks it runs the program we carry (flashes it otherwise), then relays its frames to Wolfy.
void radio_start(void);

// Instead, while the setup page is up (every 100 ms): tells it (its LED stays on), and closes
// the page when its button is held 10 s again.
void radio_setup_poll(void);
