// The Bluetooth ESP32, behind UART2 (also implements the radio_* of link.h).
#pragma once

// Checks it runs the program we carry (flashes it otherwise), then relays its frames to Wolfy.
void radio_start(void);
