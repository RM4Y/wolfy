#pragma once

// Bluetooth side (BTstack): finds Wii Remotes (1 + 2 or SYNC pressed), opens their HID
// channels and relays their reports to/from Wolfy. Call after btstack_init().
void wiimotes_init(void);
