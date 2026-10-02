// Lists the gamepads SDL sees, one JSON object per line, with the name Dolphin gives them
// (Dolphin's SDL input devices are "SDL/<n>/<name>"). Linked with the same SDL as Dolphin
// (Externals/SDL, static) so the names match exactly.
//   {"path": "/dev/input/event12", "sdl_name": "Xbox Series X Controller",
//    "name": "Microsoft Xbox Controller", "vendor": 1118, "product": 2835, "uniq": "..."}
#include <SDL3/SDL.h>
#include <stdio.h>
#include <string.h>

static void sysfs(const char* path, const char* file, char* out, size_t size)
{
  out[0] = 0;
  const char* ev = strrchr(path ? path : "", '/');
  if (!ev)
    return;
  char p[256];
  snprintf(p, sizeof p, "/sys/class/input/%s/device/%s", ev + 1, file);
  FILE* f = fopen(p, "r");
  if (!f)
    return;
  if (fgets(out, (int)size, f))
    out[strcspn(out, "\n")] = 0;
  fclose(f);
}

static void json_str(const char* s)
{
  putchar('"');
  for (; s && *s; s++)
  {
    if (*s == '"' || *s == '\\')
      putchar('\\');
    if ((unsigned char)*s >= 0x20)
      putchar(*s);
  }
  putchar('"');
}

int main(void)
{
  if (!SDL_Init(SDL_INIT_GAMEPAD))
  {
    fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
    return 1;
  }
  int count = 0;
  SDL_JoystickID* ids = SDL_GetJoysticks(&count);
  for (int i = 0; i < count; i++)
  {
    const SDL_JoystickID id = ids[i];
    const char* name = SDL_IsGamepad(id) ? SDL_GetGamepadNameForID(id) : SDL_GetJoystickNameForID(id);
    const char* path = SDL_GetJoystickPathForID(id);
    char kernel_name[256], uniq[128];
    sysfs(path, "name", kernel_name, sizeof kernel_name);
    sysfs(path, "uniq", uniq, sizeof uniq);
    printf("{\"path\": ");
    json_str(path);
    printf(", \"sdl_name\": ");
    json_str(name);
    printf(", \"name\": ");
    json_str(kernel_name);
    printf(", \"vendor\": %u, \"product\": %u, \"uniq\": ", SDL_GetJoystickVendorForID(id),
           SDL_GetJoystickProductForID(id));
    json_str(uniq);
    printf(", \"gamepad\": %s}\n", SDL_IsGamepad(id) ? "true" : "false");
  }
  SDL_free(ids);
  SDL_Quit();
  return 0;
}
