// wolfy-pads: the gamepads of the session as Eglantine sees them, one JSON object per line, in
// Eglantine's own order (SDL_GetJoysticks): its SDL (linked from the same static libSDL3 by
// build.sh), its hints and its GUID (controller name CRC cleared), its port (index among the
// joysticks of that GUID) and the default Switch mapping of its input dialog (sdl_driver.cpp:
// GetDefaultButtonBinding, GetSingleControllerMapping, GetAnalogMappingForDevice,
// GetMotionMappingForDevice). pad-config.py writes them as players 1-4 of qt-config.ini.
#include <SDL3/SDL.h>
#include <stdio.h>
#include <string.h>

#define MAX_PADS 32

static const struct { const char* key; int button; } BUTTONS[] = {
    {"a", SDL_GAMEPAD_BUTTON_EAST},       {"b", SDL_GAMEPAD_BUTTON_SOUTH},
    {"x", SDL_GAMEPAD_BUTTON_NORTH},      {"y", SDL_GAMEPAD_BUTTON_WEST},
    {"lstick", SDL_GAMEPAD_BUTTON_LEFT_STICK}, {"rstick", SDL_GAMEPAD_BUTTON_RIGHT_STICK},
    {"l", SDL_GAMEPAD_BUTTON_LEFT_SHOULDER},   {"r", SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER},
    {"plus", SDL_GAMEPAD_BUTTON_START},   {"minus", SDL_GAMEPAD_BUTTON_BACK},
    {"dleft", SDL_GAMEPAD_BUTTON_DPAD_LEFT}, {"dup", SDL_GAMEPAD_BUTTON_DPAD_UP},
    {"dright", SDL_GAMEPAD_BUTTON_DPAD_RIGHT}, {"ddown", SDL_GAMEPAD_BUTTON_DPAD_DOWN},
    {"slleft", SDL_GAMEPAD_BUTTON_LEFT_SHOULDER}, {"srleft", SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER},
    {"slright", SDL_GAMEPAD_BUTTON_LEFT_SHOULDER}, {"srright", SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER},
    {"home", SDL_GAMEPAD_BUTTON_GUIDE},   {"screenshot", SDL_GAMEPAD_BUTTON_MISC1},
};

static void json_str(const char* s) {
    putchar('"');
    for (; s && *s; s++) {
        if (*s == '"' || *s == '\\') putchar('\\');
        if ((unsigned char)*s >= 0x20) putchar(*s);
    }
    putchar('"');
}

// an Eden param package of one binding (BuildParamPackageForBinding), "" when unbound
static void param(const char* guid, int port, const SDL_GamepadBinding* b) {
    char buf[256] = "";
    if (b && b->input_type == SDL_GAMEPAD_BINDTYPE_BUTTON)
        snprintf(buf, sizeof buf, "engine:sdl,guid:%s,port:%d,button:%d", guid, port, b->input.button);
    else if (b && b->input_type == SDL_GAMEPAD_BINDTYPE_AXIS)
        snprintf(buf, sizeof buf, "engine:sdl,guid:%s,port:%d,axis:%d,threshold:0.500000,invert:+",
                 guid, port, b->input.axis.axis);
    else if (b && b->input_type == SDL_GAMEPAD_BINDTYPE_HAT) {
        const char* dir = b->input.hat.hat_mask == SDL_HAT_UP ? "up"
                        : b->input.hat.hat_mask == SDL_HAT_DOWN ? "down"
                        : b->input.hat.hat_mask == SDL_HAT_LEFT ? "left" : "right";
        snprintf(buf, sizeof buf, "engine:sdl,guid:%s,port:%d,hat:%d,direction:%s", guid, port,
                 b->input.hat.hat, dir);
    }
    json_str(buf);
}

static const SDL_GamepadBinding* find(SDL_GamepadBinding** bs, int n, int type, int what) {
    for (int i = 0; i < n; i++) {
        if (!bs[i] || bs[i]->output_type != type) continue;
        if (type == SDL_GAMEPAD_BINDTYPE_BUTTON && (int)bs[i]->output.button == what) return bs[i];
        if (type == SDL_GAMEPAD_BINDTYPE_AXIS && (int)bs[i]->output.axis.axis == what) return bs[i];
    }
    return NULL;
}

static void stick(const char* key, const char* guid, int port, SDL_GamepadBinding** bs, int n,
                  int ax, int ay) {
    const SDL_GamepadBinding* x = find(bs, n, SDL_GAMEPAD_BINDTYPE_AXIS, ax);
    const SDL_GamepadBinding* y = find(bs, n, SDL_GAMEPAD_BINDTYPE_AXIS, ay);
    printf(",\"%s\":", key);
    if (!x || !y || x->input_type != SDL_GAMEPAD_BINDTYPE_AXIS || y->input_type != SDL_GAMEPAD_BINDTYPE_AXIS) {
        json_str("");
        return;
    }
    char buf[256];
    snprintf(buf, sizeof buf,
             "engine:sdl,guid:%s,port:%d,axis_x:%d,axis_y:%d,offset_x:0.000000,offset_y:0.000000,"
             "invert_x:+,invert_y:+,deadzone:0.150000",
             guid, port, x->input.axis.axis, y->input.axis.axis);
    json_str(buf);
}

int main(void) {
    // the hints of Eglantine's SDLDriver with its default settings (no native Joy-Con/Pro driver)
    SDL_SetHint(SDL_HINT_JOYSTICK_RAWINPUT, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_STEAM, "1");
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_SENSOR_FUSION, "1");
    SDL_SetHint(SDL_HINT_AUTO_UPDATE_SENSORS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_ENHANCED_REPORTS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_JOY_CONS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_JOYCON_HOME_LED, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_COMBINE_JOY_CONS, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH_HOME_LED, "0");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_SWITCH_PLAYER_LED, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_XBOX, "0");
    if (!SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    int count = 0;
    SDL_JoystickID* ids = SDL_GetJoysticks(&count);
    char guids[MAX_PADS][33];
    for (int i = 0; ids && i < count && i < MAX_PADS; i++) {
        SDL_GUID g = SDL_GetJoystickGUIDForID(ids[i]);
        g.data[2] = g.data[3] = 0;  // Eglantine clears the controller name CRC
        for (int k = 0; k < 16; k++) snprintf(guids[i] + 2 * k, 3, "%02x", g.data[k]);
        int port = 0;
        for (int j = 0; j < i; j++) port += strcmp(guids[i], guids[j]) == 0;
        if (!SDL_IsGamepad(ids[i])) continue;
        SDL_Gamepad* pad = SDL_OpenGamepad(ids[i]);
        if (!pad) continue;
        int n = 0;
        SDL_GamepadBinding** bs = SDL_GetGamepadBindings(pad, &n);
        printf("{\"guid\":\"%s\",\"port\":%d,\"name\":", guids[i], port);
        json_str(SDL_GetGamepadName(pad));
        printf(",\"type\":");
        json_str(SDL_GetGamepadStringForType(SDL_GetGamepadType(pad)));
        for (size_t k = 0; k < sizeof BUTTONS / sizeof *BUTTONS; k++) {
            printf(",\"button_%s\":", BUTTONS[k].key);
            param(guids[i], port, find(bs, n, SDL_GAMEPAD_BINDTYPE_BUTTON, BUTTONS[k].button));
        }
        printf(",\"button_zl\":");
        param(guids[i], port, find(bs, n, SDL_GAMEPAD_BINDTYPE_AXIS, SDL_GAMEPAD_AXIS_LEFT_TRIGGER));
        printf(",\"button_zr\":");
        param(guids[i], port, find(bs, n, SDL_GAMEPAD_BINDTYPE_AXIS, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER));
        stick("lstick", guids[i], port, bs, n, SDL_GAMEPAD_AXIS_LEFTX, SDL_GAMEPAD_AXIS_LEFTY);
        stick("rstick", guids[i], port, bs, n, SDL_GAMEPAD_AXIS_RIGHTX, SDL_GAMEPAD_AXIS_RIGHTY);
        int motion = SDL_GamepadHasSensor(pad, SDL_SENSOR_GYRO) && SDL_GamepadHasSensor(pad, SDL_SENSOR_ACCEL);
        char m[160] = "";
        if (motion) snprintf(m, sizeof m, "engine:sdl,motion:0,port:%d,guid:%s", port, guids[i]);
        printf(",\"motionleft\":");
        json_str(m);
        printf(",\"motionright\":");
        json_str(m);
        printf("}\n");
        SDL_free(bs);
        SDL_CloseGamepad(pad);
    }
    SDL_free(ids);
    SDL_Quit();
    return 0;
}
