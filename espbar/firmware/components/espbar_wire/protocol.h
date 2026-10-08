// Frames exchanged with Wolfy over a WebSocket (binary messages; a frame may span messages)
//   u16 length (little endian, of what follows) | u8 type | u8 slot | payload
// and between the two ESP32 of the EspBar over a UART (wire.h).
#pragma once

#define EB_HELLO 1       // esp -> wolfy: JSON {"role": "esp", "token", "version", "id", "mac"}
                         // wifi esp -> bt esp: who are you (and announce the Wii Remotes)
                         // bt esp -> wifi esp: BD address (6) + build id (BT_ID_LEN hex chars),
                         //   slot 1 when it just started, 0 when answering
#define EB_WIIMOTE_ON 2  // esp -> wolfy: a Wii Remote is ready on <slot>, payload = BD address (6)
#define EB_WIIMOTE_OFF 3 // esp -> wolfy: the Wii Remote of <slot> is gone
#define EB_REPORT 4      // both ways: HID report of <slot> (0xA1 input / 0xA2 output + report)
#define EB_DROP 5        // wolfy -> esp: disconnect the Wii Remote of <slot> (it powers off)
#define EB_PING 6        // both ways, every 2 s
#define EB_SCAN 7        // wolfy -> esp: payload u8, 1 = look for Wii Remotes (1 + 2 / SYNC)
#define EB_STATS 8       // esp -> wolfy: text, report flow of the last 2 s (Wolfy logs it)
                         // bt esp -> wifi esp: its part of it, every 2 s (also tells it is alive)

// wifi esp <-> bt esp only: update of the Bluetooth ESP32's program, through its own app (OTA)
#define EB_OTA_BEGIN 9   // wifi -> bt: u32 size of the app
#define EB_OTA_DATA 10   // wifi -> bt: u32 offset + up to EB_OTA_CHUNK bytes of the app
#define EB_OTA_END 11    // wifi -> bt: check the app, boot it
#define EB_OTA_ACK 12    // bt -> wifi: u8 status (0 = ok) + u32 next offset expected

#define EB_SLOTS 4
#define EB_MAX_PAYLOAD 64
#define EB_OTA_CHUNK 1024
#define BT_ID_LEN 16  // hex chars of the Bluetooth program's ELF SHA-256
