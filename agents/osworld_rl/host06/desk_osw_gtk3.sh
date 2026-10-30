# Desktop start without s6 /init, identical on every system (memcompare DESK + AT-SPI env).
export DISPLAY=:1 QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 NO_AT_BRIDGE=0
H=/config; mkdir -p $H/.XDG $H/Desktop /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix
# setpriv, not runuser: runuser goes through PAM (soft nofile reset to 1024) and lingers as a root process, which breaks repeated CRIU dumps
# LibreOffice user profile: no Tip of the Day, no "first time running this version" bar, no keep-format dialog on Ctrl+S
# (an OSWorld scorer saves .xlsx with Ctrl+S and hangs on it), no Document Recovery. /config is new on every boot, so
# LibreOffice would otherwise treat every desktop as a first run (the image's share/registry .xcd does not take effect).
LO=$H/.config/libreoffice/4/user; mkdir -p $LO
cat > $LO/registrymodifications.xcu <<'XCU'
<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="LastTipOfTheDayShown" oor:op="fuse"><value>99999</value></prop></item>
<item oor:path="/org.openoffice.Setup/Product"><prop oor:name="ooSetupLastVersion" oor:op="fuse"><value>24.2</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Save/Document"><prop oor:name="WarnAlienFormat" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Recovery/RecoveryInfo"><prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
XCU
# VLC as on the OSWorld VM: web interface on :8080 with password "password" (the vlc_playing_info scorer reads
# /requests/status.xml from it, so without it every VLC task scores 0), no Privacy and Network Access dialog, and the plain X11 video output
# (the default GL output gets no X shm under Xvfb and shows a black video area, so the agent thinks nothing plays).
mkdir -p $H/.config/vlc
printf '[qt]\nqt-privacy-ask=0\n[core]\nextraintf=http\nvout=xcb_x11\nmetadata-network-access=0\n[lua]\nhttp-password=password\n[avcodec]\navcodec-hw=none\n' > $H/.config/vlc/vlcrc
if [ "$(id -u)" = 0 ]; then chown -R abc:abc $H; AS="setpriv --reuid=abc --regid=abc --init-groups --"; else AS=""; fi
Xvfb :1 -screen 0 1920x1080x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
for i in $(seq 100); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
# SAL_USE_VCLPLUGIN=gtk3: LibreOffice on GTK3 as on the OSWorld VM (Calc exposes "document spreadsheet"; needs libreoffice-gtk3, image
# localhost/webtop:ubuntu-kde-osworld-gtk3, setup/Containerfile.gtk3). GTK3 talks to at-spi by default (NO_AT_BRIDGE=0).
$AS env HOME=$H DISPLAY=:1 XDG_RUNTIME_DIR=$H/.XDG QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 NO_AT_BRIDGE=0 SAL_USE_VCLPLUGIN=gtk3 bash /defaults/startwm.sh >/tmp/wm.log 2>&1 &
wait
