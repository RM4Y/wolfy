#include "wire.h"

#include <string.h>

#define SYNC 0xEB

static uint8_t crc8(const uint8_t *p, size_t len)  // polynomial 0x07
{
    uint8_t crc = 0;
    while (len--) {
        crc ^= *p++;
        for (int i = 0; i < 8; i++)
            crc = crc & 0x80 ? (crc << 1) ^ 0x07 : crc << 1;
    }
    return crc;
}

size_t wire_encode(uint8_t *out, uint8_t type, uint8_t slot, const uint8_t *data, uint16_t len)
{
    uint16_t n = len + 2;
    out[0] = SYNC;
    out[1] = n & 0xff;
    out[2] = n >> 8;
    out[3] = type;
    out[4] = slot;
    if (len)
        memcpy(out + 5, data, len);
    out[5 + len] = crc8(out + 1, 4 + len);
    return len + 6;
}

void wire_feed(wire_rx_t *rx, const uint8_t *data, size_t len, wire_frame_cb cb)
{
    while (len--) {
        rx->buf[rx->len++] = *data++;
        for (;;) {
            bool bad = rx->buf[0] != SYNC;
            size_t n = rx->len >= 3 ? (size_t)(rx->buf[1] | rx->buf[2] << 8) : 0;
            if (!bad && rx->len >= 3)
                bad = n < 2 || n > WIRE_MAX_PAYLOAD + 2;
            if (!bad && rx->len == n + 4) {
                bad = crc8(rx->buf + 1, n + 2) != rx->buf[n + 3];
                if (!bad) {
                    cb(rx->buf[3], rx->buf[4], rx->buf + 5, n - 2);
                    rx->len = 0;
                    break;
                }
            }
            if (!bad)
                break;  // frame incomplete
            // not a frame: look for the next sync byte in what was read
            memmove(rx->buf, rx->buf + 1, --rx->len);
            if (!rx->len)
                break;
        }
    }
}
