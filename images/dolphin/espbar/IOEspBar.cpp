// Wolfy: see IOEspBar.h. Settings from the session (startup-app.sh):
//   WOLFY_ESPBAR_ADDR=host:port, WOLFY_ESPBAR_TOKEN, WOLF_SESSION_ID.
// Frames (backend/wolfy/espbar_relay.py): u16 length (LE) | u8 type | u8 slot | payload.

#include "Core/HW/WiimoteReal/IOEspBar.h"

#include <array>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>

#include <fmt/format.h>

#include "Common/Logging/Log.h"

namespace WiimoteReal
{
namespace
{
enum : u8
{
  HELLO = 1,
  WIIMOTE_ON = 2,
  WIIMOTE_OFF = 3,
  REPORT = 4,
  DROP = 5,
  PING = 6,
};
constexpr int SLOTS = 4;
constexpr size_t MAX_QUEUED = 64;

std::string IdOf(int slot, u32 generation)
{
  return fmt::format("espbar/{}/{}", slot, generation);
}

std::string Env(const char* name)
{
  const char* v = std::getenv(name);
  return v ? v : "";
}

class Link
{
public:
  static Link& Get()
  {
    static Link link;
    return link;
  }

  bool Enabled() const { return !m_host.empty(); }

  // Slots with a Wii Remote, and their generation.
  std::vector<std::pair<int, u32>> Present()
  {
    std::lock_guard lk(m_mutex);
    std::vector<std::pair<int, u32>> out;
    for (int i = 0; i < SLOTS; ++i)
      if (m_slots[i].on)
        out.emplace_back(i, m_slots[i].generation);
    return out;
  }

  bool IsOn(int slot, u32 generation)
  {
    std::lock_guard lk(m_mutex);
    return m_slots[slot].on && m_slots[slot].generation == generation;
  }

  // positive = report, negative = nothing (timeout / wakeup), zero = Wii Remote gone
  int Read(int slot, u32 generation, u8* buf)
  {
    std::unique_lock lk(m_mutex);
    auto& s = m_slots[slot];
    m_cv.wait_for(lk, std::chrono::milliseconds(200), [&] {
      return !s.reports.empty() || s.wakeup || !s.on || s.generation != generation;
    });
    if (!s.on || s.generation != generation)
      return 0;
    if (s.wakeup)
    {
      s.wakeup = false;
      return -1;
    }
    if (s.reports.empty())
      return -1;
    const auto& r = s.reports.front();
    const size_t n = std::min(r.size(), size_t(MAX_PAYLOAD));
    std::memcpy(buf, r.data(), n);
    s.reports.pop_front();
    return int(n);
  }

  void Wakeup(int slot)
  {
    std::lock_guard lk(m_mutex);
    m_slots[slot].wakeup = true;
    m_cv.notify_all();
  }

  bool Send(u8 type, int slot, const u8* data, size_t len)
  {
    std::vector<u8> frame(4 + len);
    const u16 n = u16(len + 2);
    frame[0] = n & 0xff;
    frame[1] = n >> 8;
    frame[2] = type;
    frame[3] = u8(slot);
    if (len)
      std::memcpy(frame.data() + 4, data, len);
    std::lock_guard lk(m_send_mutex);
    if (m_sock < 0)
      return false;
    size_t done = 0;
    while (done < frame.size())
    {
      const ssize_t w = send(m_sock, frame.data() + done, frame.size() - done, MSG_NOSIGNAL);
      if (w <= 0)
      {
        shutdown(m_sock, SHUT_RDWR);
        return false;
      }
      done += size_t(w);
    }
    return true;
  }

private:
  struct Slot
  {
    bool on = false;
    u32 generation = 0;
    bool wakeup = false;
    std::deque<std::vector<u8>> reports;
  };

  Link()
  {
    const std::string addr = Env("WOLFY_ESPBAR_ADDR");
    const auto colon = addr.rfind(':');
    if (colon == std::string::npos)
      return;
    m_host = addr.substr(0, colon);
    m_port = addr.substr(colon + 1);
    m_thread = std::thread([this] { Run(); });
    m_thread.detach();  // lives as long as Dolphin
  }

  int Connect()
  {
    addrinfo hints{};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* res = nullptr;
    if (getaddrinfo(m_host.c_str(), m_port.c_str(), &hints, &res) != 0)
      return -1;
    int sock = -1;
    for (addrinfo* a = res; a && sock < 0; a = a->ai_next)
    {
      sock = socket(a->ai_family, a->ai_socktype, a->ai_protocol);
      if (sock >= 0 && connect(sock, a->ai_addr, a->ai_addrlen) != 0)
      {
        close(sock);
        sock = -1;
      }
    }
    freeaddrinfo(res);
    if (sock < 0)
      return -1;
    int one = 1;
    setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    timeval tv{.tv_sec = 6, .tv_usec = 0};  // Wolfy pings every 2 s
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    return sock;
  }

  static bool RecvAll(int sock, u8* buf, size_t len)
  {
    while (len)
    {
      const ssize_t r = recv(sock, buf, len, 0);
      if (r <= 0)
        return false;
      buf += r;
      len -= size_t(r);
    }
    return true;
  }

  void SetOn(int slot, bool on)
  {
    std::lock_guard lk(m_mutex);
    auto& s = m_slots[slot];
    if (on)
      ++s.generation;
    s.on = on;
    s.reports.clear();
    m_cv.notify_all();
  }

  void Run()
  {
    const std::string hello =
        fmt::format(R"({{"role":"dolphin","session":"{}","token":"{}"}})",
                    Env("WOLF_SESSION_ID"), Env("WOLFY_ESPBAR_TOKEN"));
    while (true)
    {
      const int sock = Connect();
      if (sock < 0)
      {
        std::this_thread::sleep_for(std::chrono::seconds(2));
        continue;
      }
      {
        std::lock_guard lk(m_send_mutex);
        m_sock = sock;
      }
      Send(HELLO, 0, reinterpret_cast<const u8*>(hello.data()), hello.size());
      NOTICE_LOG_FMT(WIIMOTE, "EspBar: linked to Wolfy {}:{}", m_host, m_port);

      std::array<u8, 256> buf;
      while (RecvAll(sock, buf.data(), 2))
      {
        const u16 n = u16(buf[0] | buf[1] << 8);
        if (n < 2 || n > buf.size() || !RecvAll(sock, buf.data(), n))
          break;
        const u8 type = buf[0];
        const int slot = buf[1];
        if (slot >= SLOTS)
          continue;
        if (type == WIIMOTE_ON)
        {
          NOTICE_LOG_FMT(WIIMOTE, "EspBar: Wii Remote on slot {}", slot + 1);
          SetOn(slot, true);
        }
        else if (type == WIIMOTE_OFF)
        {
          NOTICE_LOG_FMT(WIIMOTE, "EspBar: Wii Remote of slot {} gone", slot + 1);
          SetOn(slot, false);
        }
        else if (type == REPORT && n > 2)
        {
          std::lock_guard lk(m_mutex);
          auto& s = m_slots[slot];
          if (s.on)
          {
            if (s.reports.size() >= MAX_QUEUED)
              s.reports.pop_front();
            s.reports.emplace_back(buf.begin() + 2, buf.begin() + n);
            m_cv.notify_all();
          }
        }
      }

      WARN_LOG_FMT(WIIMOTE, "EspBar: link to Wolfy lost");
      {
        std::lock_guard lk(m_send_mutex);
        m_sock = -1;
      }
      close(sock);
      for (int i = 0; i < SLOTS; ++i)
        SetOn(i, false);
      std::this_thread::sleep_for(std::chrono::seconds(2));
    }
  }

  std::string m_host, m_port;
  std::thread m_thread;
  std::mutex m_mutex;
  std::condition_variable m_cv;
  std::array<Slot, SLOTS> m_slots;
  std::mutex m_send_mutex;
  int m_sock = -1;
};
}  // namespace

WiimoteEspBar::WiimoteEspBar(int slot, u32 generation) : m_slot(slot), m_generation(generation)
{
  m_really_disconnect = true;  // Dolphin turning a Wii Remote off powers it off
}

WiimoteEspBar::~WiimoteEspBar()
{
  Shutdown();
}

std::string WiimoteEspBar::GetId() const
{
  return IdOf(m_slot, m_generation);
}

bool WiimoteEspBar::ConnectInternal()
{
  m_connected = Link::Get().IsOn(m_slot, m_generation);
  return m_connected;
}

void WiimoteEspBar::DisconnectInternal()
{
  if (m_connected && Link::Get().IsOn(m_slot, m_generation))
    Link::Get().Send(DROP, m_slot, nullptr, 0);
  m_connected = false;
}

bool WiimoteEspBar::IsConnected() const
{
  return m_connected && Link::Get().IsOn(m_slot, m_generation);
}

void WiimoteEspBar::IOWakeup()
{
  Link::Get().Wakeup(m_slot);
}

int WiimoteEspBar::IORead(u8* buf)
{
  return Link::Get().Read(m_slot, m_generation, buf);
}

int WiimoteEspBar::IOWrite(const u8* buf, size_t len)
{
  return Link::Get().Send(REPORT, m_slot, buf, len) ? int(len) : 0;
}

bool WiimoteScannerEspBar::IsReady() const
{
  return Link::Get().Enabled();
}

auto WiimoteScannerEspBar::FindAttachedWiimotes() -> FindResults
{
  FindResults results;
  if (!Link::Get().Enabled())
    return results;
  for (const auto& [slot, generation] : Link::Get().Present())
  {
    // checked before creating it: a Wiimote destroyed here would forget the id of the
    // connected one (Wiimote::Shutdown), found again and connected twice on the next scan
    if (!IsNewWiimote(IdOf(slot, generation)))
      continue;
    auto wiimote = std::make_unique<WiimoteEspBar>(slot, generation);
    NOTICE_LOG_FMT(WIIMOTE, "EspBar: found the Wii Remote of slot {}", slot + 1);
    if (wiimote->IsBalanceBoard())
      results.balance_boards.emplace_back(std::move(wiimote));
    else
      results.wii_remotes.emplace_back(std::move(wiimote));
  }
  return results;
}
}  // namespace WiimoteReal
