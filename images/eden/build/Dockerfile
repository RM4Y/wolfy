# Builds a patched Eden (the official AppImage's version) and outputs its binary,
# which replaces AppDir/shared/bin/eden (the AppImage's own libraries stay in use).
# Arch Linux + clang: the toolchain and library versions of the official AppImage.
#
#   DOCKER_BUILDKIT=1 docker build --output type=local,dest=out images/eden/build
FROM archlinux:latest AS deps

RUN pacman -Syu --noconfirm --needed base-devel clang lld llvm git cmake ninja python \
        boost catch2 enet fmt glslang libzip lz4 nlohmann-json openssl opus zlib zstd zip unzip \
        qt6-base qt6-tools qt6-charts vulkan-headers vulkan-utility-libraries libusb \
        spirv-tools spirv-headers libva libvdpau libxkbcommon brotli nasm \
        libpulse alsa-lib pipewire jack2 libx11 libxext libxrandr libxi libxcursor libxss \
        libxfixes libxinerama wayland wayland-protocols libdecor systemd-libs hidapi mesa \
    && pacman -Scc --noconfirm

ARG EDEN_TAG=v0.2.1
RUN git clone --depth 1 --branch "$EDEN_TAG" https://github.com/eden-emulator/mirror /eden
COPY patches/ /patches/
RUN cd /eden && for p in /patches/*.patch; do git apply -v "$p"; done

# Arch's libstdc++ and fmt are newer than the ones v0.2.1 was written against: headers
# Eden relied on getting transitively are force-included
ENV CXXFLAGS="-include cstring -include cstdint -include fmt/format.h"
ENV EDEN_CMAKE_ARGS="-G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang \
    -DCMAKE_CXX_COMPILER=clang++ -DYUZU_TESTS=OFF -DENABLE_QT_TRANSLATION=ON \
    -DYUZU_USE_BUNDLED_FFMPEG=ON -DYUZU_USE_EXTERNAL_SDL2=ON -DYUZU_USE_BUNDLED_OPENSSL=ON \
    -DYUZU_CMD=OFF -DENABLE_UPDATE_CHECKER=OFF"

FROM deps AS build
ARG JOBS=10
RUN cd /eden && cmake -S . -B build $EDEN_CMAKE_ARGS \
    && nice -n 19 ninja -C build -j "$JOBS" yuzu \
    && strip build/bin/eden

FROM scratch
COPY --from=build /eden/build/bin/eden /eden
