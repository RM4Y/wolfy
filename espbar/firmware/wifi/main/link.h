// Wi-Fi and the WebSocket link to Wolfy (its own FreeRTOS task, not BTstack's).
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "config.h"

void link_start(const espbar_config_t *cfg);

// Queue a frame to Wolfy (any task; dropped while Wolfy is not reached).
void link_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);

// Implemented by the program, for the Bluetooth side: BTstack on this ESP32 (one ESP32) or
// the Bluetooth ESP32 behind the UART (two, radio.c).
// A frame from Wolfy (EB_HELLO when linked: announce the Wii Remotes again).
void radio_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);
// Report flow of the last <ms> (text for Wolfy's stats).
void radio_stats(char *out, size_t size, uint32_t ms);
// Bluetooth address (false while unknown).
bool radio_bt_addr(uint8_t addr[6]);
// "1" or "2": ESP32 of this EspBar (in the HELLO).
extern const char *const radio_boards;
