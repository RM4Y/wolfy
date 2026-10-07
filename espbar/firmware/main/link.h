// Wi-Fi and the WebSocket link to Wolfy (its own FreeRTOS task, not BTstack's).
#pragma once
#include <stdint.h>

#include "config.h"

void link_start(const espbar_config_t *cfg);

// Queue a frame to Wolfy (called from BTstack's thread; dropped while Wolfy is not reached).
void link_send(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);

// Frames from Wolfy, handed to BTstack's thread (implemented in wiimotes.c).
void wiimotes_on_frame(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);
