#!/bin/bash
# Is AENV's proxy cutting slow GETs at 30 s? (1) a VM endpoint that sleeps N s, called through the proxy; (2) real /accessibility timing
# inside the VM with LibreOffice Calc open, direct vs through the proxy.
set -u; A="$HOME/.local/bin/aenv"; KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key); O=/mnt/ssd2/vikranth/osworld/traces/aenv_probe; mkdir -p $O
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
sudo docker start aenv-server >/dev/null; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
SB=$($A start kde-osworld --detach --timeout 3600 | awk '{print $NF}' | tail -1); echo "sandbox $SB"
via() { curl -s -o /dev/null -w "%{http_code} %{time_total}s" -m 700 -H "x-agentenv-sandbox-id: $SB" -H "x-agentenv-target-port: $1" "http://127.0.0.1:8000$2"; }
# (1) sleep server on :7000
$A exec $SB -- bash -c 'cat > /tmp/slow.py <<PY
import http.server, time
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(float(self.path.strip("/") or 0)); self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
http.server.ThreadingHTTPServer(("0.0.0.0", 7000), H).serve_forever()
PY
setsid nohup python3 /tmp/slow.py >/dev/null 2>&1 </dev/null &' >/dev/null; sleep 2
for s in 5 25 35 60; do echo "proxy GET sleeping ${s}s -> $(via 7000 /$s)"; done
# (2) desktop + calc, then /accessibility timing
$A upload $SB /mnt/ssd2/os4agent/agents/osworld_rl/desk_osw.sh /tmp/desk_osw.sh >/dev/null
$A exec $SB -- bash -c 'setsid nohup bash /tmp/desk_osw.sh >/dev/null 2>&1 </dev/null &' >/dev/null
for i in $(seq 120); do [ "$(via 5000 /screenshot | cut -d" " -f1)" = 200 ] && break; sleep 2; done; sleep 20
$A exec $SB -- bash -c 'su abc -c "DISPLAY=:1 setsid nohup libreoffice --calc >/dev/null 2>&1 </dev/null &"' >/dev/null; sleep 30
for i in 1 2 3; do
  d=$($A exec $SB -- bash -c 'curl -s -o /dev/null -w "%{http_code} %{time_total}s" -m 300 localhost:5000/accessibility' 2>/dev/null | tail -1)
  echo "a11y direct in VM: $d   via proxy: $(via 5000 /accessibility)"
done
$A exec $SB -- bash -c 'nproc; uptime' 2>/dev/null | tail -2
curl -s -X DELETE -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$SB >/dev/null
sudo docker stop aenv-server >/dev/null; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
