// Wolfy: Wii Remotes of the EspBar (an ESP32 connects them over Bluetooth and Wolfy relays
// them over TCP to the Dolphin of the linked device's Wii session). They behave as real Wii
// Remotes (IR pointer, extensions, MotionPlus, speaker): the HID reports pass through untouched.
#pragma once

#include <string>

#include "Core/HW/WiimoteReal/WiimoteReal.h"

namespace WiimoteReal
{
class WiimoteEspBar final : public Wiimote
{
public:
  WiimoteEspBar(int slot, u32 generation);
  ~WiimoteEspBar() override;
  std::string GetId() const override;

protected:
  bool ConnectInternal() override;
  void DisconnectInternal() override;
  bool IsConnected() const override;
  void IOWakeup() override;
  int IORead(u8* buf) override;
  int IOWrite(const u8* buf, size_t len) override;

private:
  const int m_slot;
  const u32 m_generation;  // a new connection on the same slot is another Wii Remote
  bool m_connected = false;
};

class WiimoteScannerEspBar final : public WiimoteScannerBackend
{
public:
  bool IsReady() const override;
  void Update() override {}
  void RequestStopSearching() override {}
  FindResults FindAttachedWiimotes() override;
};
}  // namespace WiimoteReal
