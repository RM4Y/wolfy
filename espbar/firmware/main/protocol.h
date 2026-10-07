// Frames exchanged with Wolfy over a WebSocket (binary messages; a frame may span messages)
//   u16 length (little endian, of what follows) | u8 type | u8 slot | payload
#pragma once

#define EB_HELLO 1       // esp -> wolfy: JSON {"role": "esp", "token", "version", "mac"}
#define EB_WIIMOTE_ON 2  // esp -> wolfy: a Wii Remote is ready on <slot>, payload = BD address (6)
#define EB_WIIMOTE_OFF 3 // esp -> wolfy: the Wii Remote of <slot> is gone
#define EB_REPORT 4      // both ways: HID report of <slot> (0xA1 input / 0xA2 output + report)
#define EB_DROP 5        // wolfy -> esp: disconnect the Wii Remote of <slot> (it powers off)
#define EB_PING 6        // both ways, every 2 s
#define EB_SCAN 7        // wolfy -> esp: payload u8, 1 = look for Wii Remotes (1 + 2 / SYNC)

#define EB_SLOTS 4
#define EB_MAX_PAYLOAD 64
