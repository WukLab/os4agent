# The original WebArena shopping site (shopping_final_0712) + a headless Chromium in one container, so a fork copies
# the site and the browser together. Chromium's DevTools port 9222 listens on all interfaces; inside the container the
# site is http://localhost (the base URL is set at setup time).
FROM shopping_final_0712:latest
# apk always exits 1 here: the image's glibc compatibility package has no apk source any more ("APK unavailable");
# so check the browser itself instead of apk's exit code.
RUN apk update; apk add --no-cache chromium font-noto; chromium-browser --version && adduser -D -u 1999 chrome
COPY chromium.ini /etc/supervisor.d/chromium.ini
# Empty the old Magento logs that ship in the image (var/log/debug.log alone is 3.1 GB): the first line Magento appends
# would otherwise copy the whole file into every container's writable layer (~3 GB written per container start).
RUN for f in /var/www/magento2/var/log/*.log; do : > "$f"; done && du -sh /var/www/magento2/var/log
EXPOSE 9222
