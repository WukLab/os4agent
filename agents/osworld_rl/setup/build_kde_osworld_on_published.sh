#!/bin/bash
# ghcr.io/wuklab/webtop:ubuntu-kde-osworld as a thin layer on the published ghcr.io/wuklab/webtop:ubuntu-kde, instead of
# SETUP.md step 3's full build: the files setup/ubuntu-img-kde-osworld.patch adds or changes (applied to ubuntu-img at
# fb313e8dd, the commit the patch is against) plus its apt packages, env and /home/user link. First checks that the
# published image's copies of the three files the patch changes are fb313e8dd's, so the layer equals the full build.
# Then copies the image into the btrfs podman store tfork / CRIU use.
#   bash setup/build_kde_osworld_on_published.sh [work dir]      (default /mnt/data/btrfs/osworld/img-build)
# Run as the repo's owner (git refuses a root caller on a user's checkout); it uses sudo -n for the podman copy.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
W=${1:-/mnt/data/btrfs/osworld/img-build}
BASE=ghcr.io/wuklab/webtop:ubuntu-kde; TAG=ghcr.io/wuklab/webtop:ubuntu-kde-osworld
CHANGED="usr/lib/python3/dist-packages/pyautogui.py usr/local/bin/wrapped-chromium usr/local/bin/wrapped-code"
rm -rf "$W" && mkdir -p "$W/src" "$W/ctx/root" && cd "$W/src"
git -C "$REPO" archive fb313e8dd ubuntu-img | tar -x
cp -a ubuntu-img ubuntu-img.orig
patch -p1 -s < "$HERE/setup/ubuntu-img-kde-osworld.patch"
docker image inspect "$BASE" >/dev/null 2>&1 || docker pull "$BASE"
cid=$(docker create "$BASE")
trap 'docker rm -f "$cid" >/dev/null' EXIT
for f in $CHANGED; do
    docker cp "$cid:/$f" "$W/base_$(basename "$f")" 2>/dev/null || { echo "base image has no /$f"; exit 1; }
    cmp -s "$W/base_$(basename "$f")" "ubuntu-img.orig/root/$f" || { echo "base /$f differs from fb313e8dd's: stop"; exit 1; }
done
docker cp "$cid:/usr/share/applications/code.desktop" "$W/base_code.desktop" 2>/dev/null \
    && grep -q '^Exec=/usr/local/bin/wrapped-code' "$W/base_code.desktop" \
    || { echo "base image's code.desktop is missing or not wrapped (the patch's Dockerfile fix): stop"; exit 1; }
echo "base image matches fb313e8dd for the files the patch changes"
(cd ubuntu-img/root && diff -rq ../../ubuntu-img.orig/root . || true) | sed -n 's#^Only in \./*\(.*\): \(.*\)#\1/\2#p; s#^Files .* and \./\(.*\) differ#\1#p' \
    | while read -r p; do p=${p#./}; mkdir -p "$W/ctx/root/$(dirname "$p")"; cp -a "ubuntu-img/root/$p" "$W/ctx/root/$p"; done
# Ubuntu's LibreOffice links /usr/lib/libreoffice/share/registry -> /etc/libreoffice/registry; COPY can't write through a
# symlinked directory, so the registry file goes to the link's target
reg=$(docker run --rm --entrypoint readlink "$BASE" -f /usr/lib/libreoffice/share/registry)
if [ "$reg" != /usr/lib/libreoffice/share/registry ]; then
    mkdir -p "$W/ctx/root$reg" && mv "$W/ctx/root/usr/lib/libreoffice/share/registry/"* "$W/ctx/root$reg/"
    rm -r "$W/ctx/root/usr/lib/libreoffice"
fi
find "$W/ctx/root" -type f | sed "s#$W/ctx/root##" | sort
cat > "$W/ctx/Dockerfile" <<EOF
# the OSWorld part of setup/ubuntu-img-kde-osworld.patch on top of the published KDE webtop
FROM $BASE
ENV QT_ACCESSIBILITY=1 \\
    QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 \\
    NO_AT_BRIDGE=0
RUN apt-get update && \\
  DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \\
    at-spi2-core libatk-adaptor python3-flask python3-lxml python3-numpy python3-pyatspi python3-requests socat wmctrl && \\
  apt-get autoclean && rm -rf /var/lib/apt/lists/* /var/tmp/* /tmp/* && \\
  { [ -e /home/user ] || ln -s /config /home/user; }
COPY /root /
EXPOSE 3000 5000
EOF
docker build --network host -t "$TAG" "$W/ctx"
sudo -n env CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf PODMAN_TFORK_SKIP_SYSCTL=1 \
    CONTAINERS_CONF="$REPO/agents/webarena_rl/containers-os4agent.conf" "$REPO/podman-tfork.sh" pull "docker-daemon:$TAG"
echo "built $TAG"
