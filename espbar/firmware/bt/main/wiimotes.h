#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Bluetooth side (BTstack): finds Wii Remotes (1 + 2 or SYNC pressed), opens their HID
// channels and relays their reports to/from Wolfy. Call after btstack_init().
void wiimotes_init(void);

// Frames from Wolfy (any task): handed to BTstack's thread.
void wiimotes_on_frame(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);

// Report flow since the last call, <ms> ago (text for Wolfy's stats).
void wiimotes_stats(char *out, size_t size, uint32_t ms);

// Implemented by the program: a frame to Wolfy (from BTstack's thread), straight over Wi-Fi
// (one ESP32) or through the Wi-Fi ESP32 (two).
void link_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);
