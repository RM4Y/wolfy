// The UART between the two ESP32 of the EspBar (921600 baud): frames of protocol.h, framed
// so that a lost byte or the Bluetooth ESP32's boot messages don't desync the link
//   0xEB | u16 length (little endian, of type + slot + payload) | u8 type | u8 slot | payload | crc8
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "protocol.h"

#define WIRE_BAUD 921600
#define WIRE_MAX_PAYLOAD (EB_OTA_CHUNK + 4)
#define WIRE_SIZE(payload) ((payload) + 6)
#define WIRE_MAX WIRE_SIZE(WIRE_MAX_PAYLOAD)

// Writes the frame to out (WIRE_SIZE(len) bytes), returns its size.
size_t wire_encode(uint8_t *out, uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);

typedef void (*wire_frame_cb)(uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len);

typedef struct {
    uint8_t buf[WIRE_MAX];
    size_t len;
} wire_rx_t;

// Bytes read from the UART: calls cb for each valid frame, skips anything else.
void wire_feed(wire_rx_t *rx, const uint8_t *data, size_t len, wire_frame_cb cb);
