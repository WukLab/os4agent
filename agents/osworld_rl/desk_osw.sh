# Desktop start without s6 /init, identical on every system (memcompare DESK + AT-SPI env).
export DISPLAY=:1 QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 NO_AT_BRIDGE=0
H=/config; mkdir -p $H/.XDG $H/Desktop /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix
# setpriv, not runuser: runuser goes through PAM (soft nofile reset to 1024) and lingers as a root process, which breaks repeated CRIU dumps
if [ "$(id -u)" = 0 ]; then chown -R abc:abc $H; AS="setpriv --reuid=abc --regid=abc --init-groups --"; else AS=""; fi
Xvfb :1 -screen 0 1920x1080x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
for i in $(seq 100); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
$AS env HOME=$H DISPLAY=:1 XDG_RUNTIME_DIR=$H/.XDG QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 NO_AT_BRIDGE=0 bash /defaults/startwm.sh >/tmp/wm.log 2>&1 &
wait
