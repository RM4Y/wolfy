# Environment that builds the patched Switch emulator (build.sh, update-emulator.py, Wolfy): the
# toolchain of the fork's Linux PGO release (its .github/workflows), so the binary runs on the
# release AppImage's libraries. The version comes from emulator.version (build arguments, all
# required). Each argument is declared right before its step, so a new version reuses the layers above.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg python3-pip \
        autoconf cmake g++ gcc glslang-tools libglu1-mesa-dev \
        libpulse-dev libtool libudev-dev libxkbcommon-x11-0 \
        mesa-common-dev nasm ninja-build qt6-base-private-dev \
        qt6-charts-dev qt6-tools-dev libavfilter-dev libavcodec-dev \
        libswscale-dev pkg-config zlib1g-dev libva-dev libvdpau-dev \
        spirv-tools spirv-headers libusb-1.0-0-dev \
        libboost-dev libboost-fiber-dev libboost-context-dev \
        libopus-dev libasound2-dev \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
        libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    && rm -rf /var/lib/apt/lists/*

ARG EMU_LLVM
ENV LLVM=$EMU_LLVM
RUN test -n "$LLVM" || { echo "EMU_LLVM requis (emulator.version)"; exit 1; } \
    && curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key >/etc/apt/trusted.gpg.d/apt.llvm.org.asc \
    && echo "deb http://apt.llvm.org/noble/ llvm-toolchain-noble-$LLVM main" >/etc/apt/sources.list.d/llvm.list \
    && apt-get update && apt-get install -y --no-install-recommends "clang-$LLVM" "lld-$LLVM" \
    && rm -rf /var/lib/apt/lists/*

# cmake: Ubuntu 24.04 has 3.28, the forks need 3.31+ (the GitHub runners have a newer one)
ARG EMU_QT
RUN test -n "$EMU_QT" || { echo "EMU_QT requis (emulator.version)"; exit 1; } \
    && pip install --break-system-packages aqtinstall "cmake>=3.31,<4" \
    && aqt install-qt -O /opt/qt linux desktop "$EMU_QT" linux_gcc_64 -m qtcharts \
    && ln -s "$EMU_QT" /opt/qt/current

# on the GitHub runners but not in this image (fetching and patching the bundled dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends patch patchelf unzip zip xz-utils bzip2 file wget perl make \
    && rm -rf /var/lib/apt/lists/*

# the bundled OpenSSL calls plain "clang"
RUN ln -s "clang-$LLVM" /usr/bin/clang && ln -s "clang++-$LLVM" /usr/bin/clang++

# the sources of EMU_TAG and the version labels the build embeds (GIT-*); /emulator-version: the
# version file of these sources, written next to the binary (patched/bin) and to images/switch by
# compile.sh; /emulator-source-id: this checkout (new dates on every file: compile.sh then starts
# a clean build)
ARG EMU_NAME
ARG EMU_REPO
ARG EMU_BINARY
ARG EMU_TAG
ARG EMU_DATE
ARG EMU_COMMIT
RUN test -n "$EMU_REPO" -a -n "$EMU_BINARY" -a -n "$EMU_TAG" -a -n "$EMU_COMMIT" \
        || { echo "EMU_REPO, EMU_BINARY, EMU_TAG et EMU_COMMIT requis (emulator.version)"; exit 1; } \
    && git init -q /src && cd /src \
    && git fetch -q --depth 1 "https://github.com/$EMU_REPO" "$EMU_COMMIT" \
    && git checkout -q FETCH_HEAD \
    && echo "$EMU_COMMIT" >GIT-COMMIT && echo "$EMU_TAG" >GIT-REFSPEC && echo "$EMU_TAG" >GIT-TAG \
    && printf 'EMU_NAME=%s\nEMU_REPO=%s\nEMU_BINARY=%s\nEMU_TAG=%s\nEMU_DATE=%s\nEMU_COMMIT=%s\nEMU_LLVM=%s\nEMU_QT=%s\n' \
        "$EMU_NAME" "$EMU_REPO" "$EMU_BINARY" "$EMU_TAG" "$EMU_DATE" "$EMU_COMMIT" "$EMU_LLVM" "$EMU_QT" >/emulator-version \
    && echo "$EMU_REPO $EMU_COMMIT $(date +%s%N)" >/emulator-source-id

WORKDIR /src
