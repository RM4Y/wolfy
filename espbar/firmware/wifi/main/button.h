// The button and the LED of the EspBar, on this ESP32 (the Bluetooth one only looks when told).
#pragma once

// Watches the button (its own task): Wii Remote search, setup page.
void button_start(void);

// Instead, while the setup page is up (every 100 ms): LED on, held 10 s again closes it.
void button_setup_poll(void);
