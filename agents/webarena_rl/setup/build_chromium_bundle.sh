#!/bin/bash
# A self-contained newer Chromium for the Alpine 3.16 WebArena image, without touching the image's own libraries:
# Alpine 3.20's chromium (131) plus every shared library it needs and that release's musl loader, under /opt/chr;
# the binaries' ELF interpreter is set to /opt/chr/lib/ld-musl-x86_64.so.1 and every ELF's rpath to /opt/chr/lib
# (patchelf), so /proc/self/exe stays chromium (it re-execs itself for renderers) and nothing reads /lib or /usr/lib.
# Built in docker (podman containers here have no outbound network: host FORWARD policy is DROP).
#   bash setup/build_chromium_bundle.sh [alpine release]   -> /mnt/data/ssd4/yutong/tfork_build/chr_bundle/chr-<ver>.tar
# Also socat (CDP relay: Chromium 131 ignores --remote-debugging-address and listens on 127.0.0.1 only).
# Use: podman cp the tar into the container, tar -C / -xf, run /opt/chr/chromium/chromium --headless=old ...
set -euo pipefail
REL=${1:-3.20}
OUT=/mnt/data/ssd4/yutong/tfork_build/chr_bundle
mkdir -p "$OUT"
docker run --rm -v "$OUT":/out alpine:"$REL" sh -euc '
apk add --no-cache chromium socat patchelf > /dev/null
V=$(chromium-browser --version | awk "{print \$2}")
mkdir -p /opt/chr/lib /opt/chr/bin
cp -a /usr/lib/chromium /opt/chr/chromium
cp -L /usr/bin/socat /opt/chr/bin/socat
# every shared library any ELF in the chromium dir needs (ldd lists the loader as /lib/ld-musl-x86_64.so.1)
for f in $(find /opt/chr/chromium /opt/chr/bin -type f); do
    if head -c 4 "$f" | grep -q ELF; then ldd "$f" 2>/dev/null | awk "/=>/ {print \$3}"; fi
done | sort -u | while read -r so; do [ -f "$so" ] && cp -L "$so" /opt/chr/lib/; done
cp -L /lib/ld-musl-x86_64.so.1 /opt/chr/lib/ld-musl-x86_64.so.1
cp -L /lib/ld-musl-x86_64.so.1 /opt/chr/lib/libc.musl-x86_64.so.1
for f in $(find /opt/chr -type f); do
    head -c 4 "$f" | grep -q ELF || continue
    case "$f" in */ld-musl-x86_64.so.1|*/libc.musl-x86_64.so.1) continue;; esac
    patchelf --set-rpath /opt/chr/lib "$f"
    if patchelf --print-interpreter "$f" > /dev/null 2>&1; then patchelf --set-interpreter /opt/chr/lib/ld-musl-x86_64.so.1 "$f"; fi
done
echo "$V" > /opt/chr/VERSION
tar -C / -cf /out/chr-$V.tar opt/chr
echo "chromium $V: $(ls /opt/chr/lib | wc -l) libs, $(du -sh /opt/chr | cut -f1)"
'
ls -la "$OUT"
