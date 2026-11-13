# syntax=docker/dockerfile:1

# ==== Selkies base on Ubuntu 22.04 (jammy) ====
# linuxserver only publishes baseimage-selkies for noble/resolute, and
# GNOME 42 (the OSWorld VM's desktop) only exists on jammy. These stages
# rebuild that base for jammy, adapted from
# linuxserver/docker-baseimage-selkies@7842dd7 (ubunturesolute): same
# selkies/pixelflux/pcmflux releases (cp310 wheels), X11 only (no
# labwc/wayland, pelorus or docker-in-docker), stock jammy Xvfb. Its
# s6 services and defaults are vendored in base/root/.
FROM ghcr.io/linuxserver/baseimage-alpine:3.24 AS frontend

ARG SELKIES_RELEASE=2.1.0

RUN \
  echo "**** install build packages ****" && \
  apk add \
    cmake \
    git \
    nodejs \
    npm

RUN \
  echo "**** ingest code ****" && \
  git clone \
    https://github.com/selkies-project/selkies.git \
    /src && \
  cd /src && \
  git checkout -f ${SELKIES_RELEASE}

RUN \
  echo "**** build shared core library ****" && \
  cd /src/addons/selkies-web-core && \
  npm install && \
  npm run build && \
  echo "**** build multiple dashboards ****" && \
  DASHBOARDS="selkies-dashboard selkies-dashboard-wish" && \
  mkdir /buildout && \
  for DASH in $DASHBOARDS; do \
    cd /src/addons/$DASH && \
    npm install && \
    npm run build && \
    mkdir -p dist/src && \
    cp ../selkies-web-core/dist/selkies-core.js dist/src/ && \
    cp ../universal-touch-gamepad/universalTouchGamepad.js dist/src/ && \
    mkdir -p /buildout/$DASH && \
    cp -ar dist/* /buildout/$DASH/; \
  done

FROM ghcr.io/linuxserver/baseimage-ubuntu:jammy AS interposers

ARG SELKIES_RELEASE=2.1.0

RUN \
  echo "**** interposer build deps ****" && \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
    build-essential \
    gcc-multilib \
    git

RUN \
  echo "**** ingest selkies addons ****" && \
  git clone \
    https://github.com/selkies-project/selkies.git \
    /src && \
  cd /src && \
  git checkout -f ${SELKIES_RELEASE} && \
  mkdir -p /buildout/usr/lib /buildout/opt/lib && \
  echo "**** build selkies input interposer ****" && \
  cd /src/addons/input-interposer && \
  gcc -shared -fPIC -ldl \
    -o /buildout/usr/lib/selkies_input_interposer.so \
    input_interposer.c && \
  echo "**** link legacy joystick interposer name ****" && \
  ln -s \
    selkies_input_interposer.so \
    /buildout/usr/lib/selkies_joystick_interposer.so && \
  echo "**** build selkies webcam interposer ****" && \
  cd /src/addons/v4l2-interposer && \
  gcc -shared -fPIC -ldl -pthread \
    -o /buildout/usr/lib/selkies_v4l2_interposer.so \
    v4l2_interposer.c && \
  echo "**** build selkies fake udev ****" && \
  cd /src/addons/fake-udev && \
  make && \
  mv \
    libudev.so.1.0.0-fake \
    /buildout/opt/lib/libudev.so.1.0.0-fake

FROM ghcr.io/linuxserver/baseimage-ubuntu:jammy AS selkies-base

ARG SELKIES_RELEASE=2.1.0
ARG PIXELFLUX_RELEASE=2.2.1
ARG PCMFLUX_RELEASE=2.2.0

ENV DISPLAY=:1 \
    PERL5LIB=/usr/local/bin \
    HOME=/config \
    START_DOCKER=false \
    PIXELFLUX_WAYLAND=false \
    PULSE_RUNTIME_PATH=/defaults \
    SELKIES_INTERPOSER=/usr/lib/selkies_input_interposer.so \
    SELKIES_WEBCAM_INTERPOSER=/usr/lib/selkies_v4l2_interposer.so \
    NVIDIA_DRIVER_CAPABILITIES=all \
    DISABLE_DRI3=true \
    SELKIES_ENCODER="h264enc,h265enc,vp8enc,vp9enc,av1enc,jpeg" \
    SELKIES_ENABLE_BASIC_AUTH=false \
    SELKIES_VIDEO_STREAMING_MODE=false \
    SELKIES_ALLOWED_ORIGINS="*" \
    SELKIES_RATE_CONTROL_MODE="crf,cbr" \
    SHELL=/bin/bash \
    __GL_SYNC_TO_VBLANK=0 \
    TITLE=Selkies

RUN \
  echo "**** dev deps ****" && \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
    python3-dev && \
  echo "**** enable locales ****" && \
  sed -i \
    '/locale/d' \
    /etc/dpkg/dpkg.cfg.d/excludes && \
  echo "**** install deps ****" && \
  DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
    at-spi2-core \
    breeze-cursor-theme \
    ca-certificates \
    console-data \
    dbus-x11 \
    file \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-noto-core \
    gir1.2-atspi-2.0 \
    gir1.2-gtk-3.0 \
    intel-media-va-driver \
    iproute2 \
    kbd \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libev4 \
    libfontenc1 \
    libfreetype6 \
    libgbm1 \
    libgcrypt20 \
    libgirepository-1.0-1 \
    libgl1-mesa-dri \
    libglu1-mesa \
    libgnutls30 \
    libgtk-3-0 \
    libjpeg-turbo8 \
    libnginx-mod-http-fancyindex \
    libnotify-bin \
    libnss3 \
    libopus0 \
    libp11-kit0 \
    libpam0g \
    libtasn1-6 \
    libvulkan1 \
    libx11-6 \
    libx264-163 \
    libxau6 \
    libxcb1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcursor1 \
    libxdmcp6 \
    libxext6 \
    libxfixes3 \
    libxfont2 \
    libxinerama1 \
    libxkbcommon-x11-0 \
    libxshmfence1 \
    libxtst6 \
    locales-all \
    mesa-va-drivers \
    mesa-vulkan-drivers \
    nginx \
    openbox \
    openssh-client \
    openssl \
    pciutils \
    procps \
    psmisc \
    pulseaudio \
    pulseaudio-utils \
    python3 \
    python3-gi \
    python3-venv \
    software-properties-common \
    ssl-cert \
    stterm \
    sudo \
    tar \
    util-linux \
    x11-apps \
    x11-common \
    x11-utils \
    x11-xkb-utils \
    x11-xserver-utils \
    xauth \
    xclip \
    xcvt \
    xdg-utils \
    xdotool \
    xfonts-base \
    xkb-data \
    xsel \
    xserver-common \
    xserver-xorg-core \
    xsettingsd \
    xterm \
    xutils \
    xvfb \
    zlib1g \
    zstd && \
  echo "**** install selkies ****" && \
  python3 \
    -m venv \
    --system-site-packages \
    /lsiopy && \
  pip install --upgrade pip && \
  pip install \
    https://github.com/selkies-project/pixelflux/releases/download/${PIXELFLUX_RELEASE}/pixelflux-${PIXELFLUX_RELEASE}-cp310-cp310-manylinux_2_28_x86_64.whl \
    https://github.com/selkies-project/pcmflux/releases/download/${PCMFLUX_RELEASE}/pcmflux-${PCMFLUX_RELEASE}-cp310-cp310-manylinux_2_28_x86_64.whl \
    https://github.com/selkies-project/selkies/releases/download/${SELKIES_RELEASE}/selkies-${SELKIES_RELEASE#v}-py3-none-any.whl && \
  pip install setuptools && \
  echo "**** add icon ****" && \
  mkdir -p \
    /usr/share/selkies/www && \
  curl -o \
    /usr/share/selkies/www/favicon.ico \
    https://raw.githubusercontent.com/linuxserver/docker-templates/refs/heads/master/linuxserver.io/img/selkies-icon.ico && \
  echo "**** openbox tweaks ****" && \
  sed -i \
    -e 's/NLIMC/NLMC/g' \
    -e '/debian-menu/d' \
    -e 's|</applications>|  <application class="*"><maximized>yes</maximized></application>\n</applications>|' \
    -e 's|</keyboard>|  <keybind key="C-S-d"><action name="ToggleDecorations"/></keybind>\n</keyboard>|' \
    -e 's|<number>4</number>|<number>1</number>|' \
    /etc/xdg/openbox/rc.xml && \
  echo "**** user perms ****" && \
  sed -e 's/%sudo	ALL=(ALL:ALL) ALL/%sudo ALL=(ALL:ALL) NOPASSWD: ALL/g' \
    -i /etc/sudoers && \
  echo "abc:abc" | chpasswd && \
  usermod -s /bin/bash abc && \
  usermod -aG sudo abc && \
  echo "**** proot-apps ****" && \
  mkdir /proot-apps/ && \
  PAPPS_RELEASE=$(curl -sX GET "https://api.github.com/repos/linuxserver/proot-apps/releases/latest" \
    | jq -r '.tag_name') && \
  curl -L https://github.com/linuxserver/proot-apps/releases/download/${PAPPS_RELEASE}/proot-apps-x86_64.tar.gz \
    | tar -xzf - -C /proot-apps/ && \
  echo "${PAPPS_RELEASE}" > /proot-apps/pversion && \
  echo "**** cleanup ****" && \
  apt-get purge -y --autoremove \
    python3-dev && \
  apt-get autoclean && \
  rm -rf \
    /config/.cache \
    /root/.cache \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*

COPY /base/root /
COPY --from=frontend /buildout /usr/share/selkies
COPY --from=interposers /buildout /

# ==== GNOME 42 desktop ====
FROM selkies-base

# set version label
ARG BUILD_DATE
ARG VERSION
LABEL build_version="Linuxserver.io version:- ${VERSION} Build-date:- ${BUILD_DATE}"
LABEL maintainer="thelamer"
ARG DEBIAN_FRONTEND="noninteractive"

# title. NO_WEBCAM: the jammy base (like upstream's newer bases) would
# otherwise LD_PRELOAD its v4l2 webcam interposer into every process.
ENV TITLE="Ubuntu GNOME" \
    NO_GAMEPAD=true \
    NO_WEBCAM=true

# Disable libuv io_uring backend container-wide so VSCode's bundled
# Electron/Node runtime (and anything else libuv-based) falls back to
# epoll. CRIU can't dump anon_inode:[io_uring] fds, so leaving this on
# breaks checkpoint of any process that ends up using the io_uring path
# (libuv >=1.49 enables it by default for fs ops).
ENV UV_USE_IO_URING=0

# Force en_US.UTF-8 so Chrome picks up its full prepopulated search-
# engine list (Google, Bing, Yahoo, DuckDuckGo, Ecosia). The base
# image's C.UTF-8 default makes Chrome seed only DuckDuckGo, which
# breaks agent flows like "set Bing as the default search engine".
# Generated below in the apt install layer; declaring here so every
# child process inherits it.
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

RUN \
  echo "**** locale ****" && \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y locales && \
  locale-gen en_US.UTF-8 && \
  update-locale LANG=en_US.UTF-8 && \
  echo "**** add icon ****" && \
  curl -o \
    /usr/share/selkies/www/icon.png \
    https://raw.githubusercontent.com/linuxserver/docker-templates/master/linuxserver.io/img/webtop-logo.png && \
  echo "**** add google chrome repo (the OSWorld VM's browser) ****" && \
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list && \
  echo "**** install packages ****" && \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive \
  apt-get install --no-install-recommends -y \
    dconf-cli \
    eog \
    fonts-ubuntu \
    gedit \
    gnome-control-center \
    gnome-shell-extension-appindicator \
    gnome-shell-extension-desktop-icons-ng \
    gnome-shell-extension-ubuntu-dock \
    gnome-software \
    gnome-terminal \
    gnome-user-docs \
    google-chrome-stable \
    nautilus \
    network-manager \
    ubuntu-docs \
    ubuntu-session \
    ubuntu-settings \
    xdg-user-dirs \
    yaru-theme-gtk \
    yaru-theme-icon \
    yelp \
    zenity && \
  echo "**** application tweaks ****" && \
  sed -i \
    's#^Exec=/usr/bin/google-chrome-stable#Exec=/usr/local/bin/wrapped-chrome#g' \
    /usr/share/applications/google-chrome.desktop && \
  grep -q wrapped-chrome /usr/share/applications/google-chrome.desktop && \
  # The OSWorld VM's dock has Ubuntu Software (the snap store) under
  # snap-store_ubuntu-software.desktop. That launcher ships in /root and
  # runs gnome-software; drop gnome-software's own entry so its windows
  # group under that launcher, which also drops its shell search
  # provider. Its autostart would only sit in the background refreshing.
  rm -f /usr/share/applications/org.gnome.Software.desktop \
        /etc/xdg/autostart/gnome-software-service.desktop && \
  echo "**** gnome tweaks ****" && \
  # gnome-shell takes /run/systemd/seats to mean logind is running, then
  # crashes on the missing org.freedesktop.login1. Make sure no package
  # install left it behind.
  rm -rf /run/systemd/seats /run/systemd/sessions /run/systemd/users && \
  # gsd-power exits without logind + UPower, and as a RequiredComponent
  # that drops the whole session onto the fail screen. Its job (dim,
  # blank, suspend) is unwanted in a streamed container anyway.
  sed -i 's/org.gnome.SettingsDaemon.Power;//' \
    /usr/share/gnome-session/sessions/ubuntu.session && \
  rm -f /etc/xdg/autostart/org.gnome.SettingsDaemon.Power.desktop && \
  echo "**** cleanup ****" && \
  apt-get autoclean && \
  rm -rf \
    /config/.cache \
    /config/.launchpadlib \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*

# ==== custom packages ====
ENV SAL_USE_VCLPLUGIN=gtk3
RUN \
  echo "**** add microsoft repo for vscode ****" && \
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/packages.microsoft.gpg && \
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" \
    > /etc/apt/sources.list.d/vscode.list && \
  echo "**** install custom apps ****" && \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive \
  apt-get install --no-install-recommends -y \
    adwaita-icon-theme \
    code \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-noto-core \
    gimp \
    gimp-data-extras \
    gtk2-engines-pixbuf \
    hicolor-icon-theme \
    libaa1 \
    libqt6svg6 \
    librsvg2-common \
    libwmf-0.2-7 \
    mypaint-brushes \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-gtk3 \
    libreoffice-style-yaru \
    libreoffice-writer \
    thunderbird \
    tmux \
    ubuntu-wallpapers \
    ubuntu-wallpapers-jammy \
    vlc && \
  echo "**** wire up CRIU-friendly wrappers for vscode + thunderbird ****" && \
  # code >=1.143 ships com.microsoft.VSCode.desktop; move it back to the
  # code.desktop id the OSWorld VM (code 1.85) has, for the dock.
  sed -i \
    's#^Exec=/usr/share/code/code#Exec=/usr/local/bin/wrapped-code#g' \
    /usr/share/applications/com.microsoft.VSCode.desktop && \
  mv /usr/share/applications/com.microsoft.VSCode.desktop \
     /usr/share/applications/code.desktop && \
  sed -i \
    's#^Exec=thunderbird #Exec=/usr/local/bin/wrapped-thunderbird #g' \
    /usr/share/applications/thunderbird.desktop && \
  echo "**** suppress autostarts that derail OSWorld tasks ****" && \
  # Thunderbird's package ships /etc/xdg/autostart/thunderbird.desktop
  # that fires on GNOME login, then on first run pops the privacy
  # notice + opens the browser to its donation URL. Both steal focus
  # from whatever the agent is doing. Drop the autostart entry; the
  # dock launcher stays, so Thunderbird-specific tasks still work — the
  # agent just has to launch it explicitly.
  rm -f /etc/xdg/autostart/thunderbird*.desktop \
        /etc/xdg/autostart/org.mozilla.thunderbird*.desktop && \
  echo "**** cleanup ****" && \
  apt-get autoclean && \
  rm -rf \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /tmp/*
# ==== end custom packages ====

# ==== AT-SPI accessibility tree for the bench ====
# The bench reads the a11y tree over AT-SPI (pyatspi, as OSWorld does).
# GTK3, Qt, LibreOffice and Thunderbird register on their own once
# toolkit-accessibility is on (see /etc/dconf/db/local.d/00-webtop);
# GIMP 2.10 is GTK2 and needs the gail + atk-bridge GTK2 modules.
# Chrome and VS Code get --force-renderer-accessibility in their
# wrappers. (xdotool for the pyautogui shim comes with the base.)
RUN \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive \
  apt-get install --no-install-recommends -y \
    libatk-adaptor \
    libgail-common \
    python3-pyatspi && \
  apt-get autoclean && \
  rm -rf /var/lib/apt/lists/* /var/tmp/* /tmp/*

# add local files
COPY /root /

# Compile the system-wide GNOME defaults shipped in
# root/etc/dconf/db/local.d/ (no lock, idle, animations; dock
# favorites). They only replace schema defaults — users and agents can
# still change any of them with gsettings.
RUN dconf update

# ports and volumes
EXPOSE 3000 3001
VOLUME /config
