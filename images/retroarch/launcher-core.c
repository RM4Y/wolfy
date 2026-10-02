/* Libretro "launcher" core: runs a standalone emulator (RPCS3, Vita3K) from the RetroArch XMB.
 *
 * Loading a game starts `/opt/wolfy/bin/ps-launch EMU <content path>` in its own process group;
 * the core shows a black screen behind it and closes the content (back to the XMB) when the
 * emulator exits. Closing the content from the RetroArch menu stops the emulator.
 *
 * Built once per emulator: -DEMU='"rpcs3"' -DLIB_NAME='"RPCS3"' -DEXTS='"bin"'
 */
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "libretro.h"

#define WIDTH 320
#define HEIGHT 180
#define LAUNCHER "/opt/wolfy/bin/ps-launch"
#define PIDFILE "/tmp/wolfy-external.pid"

static retro_environment_t environ_cb;
static retro_video_refresh_t video_cb;
static uint32_t frame[WIDTH * HEIGHT];
static pid_t child = -1;
static int finished;

static void stop_child(void)
{
   if (child <= 0)
      return;
   kill(-child, SIGTERM);
   for (int i = 0; i < 50 && waitpid(child, NULL, WNOHANG) == 0; i++)
      usleep(100000);
   kill(-child, SIGKILL);
   waitpid(child, NULL, 0);
   child = -1;
   unlink(PIDFILE); /* written by ps-launch, read by the HOME combo */
}

void retro_set_environment(retro_environment_t cb)
{
   bool no_game = false;
   environ_cb = cb;
   cb(RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME, &no_game);
}

void retro_set_video_refresh(retro_video_refresh_t cb) { video_cb = cb; }
void retro_set_audio_sample(retro_audio_sample_t cb) { (void)cb; }
void retro_set_audio_sample_batch(retro_audio_sample_batch_t cb) { (void)cb; }
void retro_set_input_poll(retro_input_poll_t cb) { (void)cb; }
void retro_set_input_state(retro_input_state_t cb) { (void)cb; }
void retro_init(void) {}
void retro_deinit(void) { stop_child(); }
unsigned retro_api_version(void) { return RETRO_API_VERSION; }

void retro_get_system_info(struct retro_system_info *info)
{
   memset(info, 0, sizeof(*info));
   info->library_name = LIB_NAME;
   info->library_version = "wolfy";
   info->valid_extensions = EXTS;
   info->need_fullpath = true;
   info->block_extract = true;
}

void retro_get_system_av_info(struct retro_system_av_info *info)
{
   memset(info, 0, sizeof(*info));
   info->geometry.base_width = info->geometry.max_width = WIDTH;
   info->geometry.base_height = info->geometry.max_height = HEIGHT;
   info->geometry.aspect_ratio = 16.0f / 9.0f;
   info->timing.fps = 60.0;
   info->timing.sample_rate = 48000.0;
}

void retro_set_controller_port_device(unsigned port, unsigned device) { (void)port; (void)device; }
void retro_reset(void) {}

bool retro_load_game(const struct retro_game_info *game)
{
   enum retro_pixel_format fmt = RETRO_PIXEL_FORMAT_XRGB8888;
   if (!game || !game->path || !environ_cb(RETRO_ENVIRONMENT_SET_PIXEL_FORMAT, &fmt))
      return false;
   finished = 0;
   child = fork();
   if (child < 0)
      return false;
   if (child == 0)
   {
      setpgid(0, 0);
      execl(LAUNCHER, LAUNCHER, EMU, game->path, (char *)NULL);
      _exit(127);
   }
   setpgid(child, child);
   return true;
}

bool retro_load_game_special(unsigned type, const struct retro_game_info *info, size_t num)
{
   (void)type; (void)info; (void)num;
   return false;
}

void retro_unload_game(void) { stop_child(); }

void retro_run(void)
{
   if (child > 0 && waitpid(child, NULL, WNOHANG) == child)
   {
      child = -1;
      finished = 1;
   }
   video_cb(frame, WIDTH, HEIGHT, WIDTH * sizeof(uint32_t));
   if (finished)
   {
      finished = 0;
      environ_cb(RETRO_ENVIRONMENT_SHUTDOWN, NULL);
   }
   else
   {
      /* nothing to emulate: don't spin the CPU behind the emulator */
      struct timespec ts = {0, 15 * 1000 * 1000};
      nanosleep(&ts, NULL);
   }
}

unsigned retro_get_region(void) { return RETRO_REGION_NTSC; }
size_t retro_serialize_size(void) { return 0; }
bool retro_serialize(void *data, size_t size) { (void)data; (void)size; return false; }
bool retro_unserialize(const void *data, size_t size) { (void)data; (void)size; return false; }
void *retro_get_memory_data(unsigned id) { (void)id; return NULL; }
size_t retro_get_memory_size(unsigned id) { (void)id; return 0; }
void retro_cheat_reset(void) {}
void retro_cheat_set(unsigned index, bool enabled, const char *code) { (void)index; (void)enabled; (void)code; }
