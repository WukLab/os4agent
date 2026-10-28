#!/bin/bash
# Can the host reach a sandbox directly (no proxy)? Find its host_interaction_ip and time a slow GET to it.
A="$HOME/.local/bin/aenv"; KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
sudo docker start aenv-server >/dev/null; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
SB=$($A start kde-osworld --detach --timeout 1800 | awk '{print $NF}' | tail -1); echo "sandbox $SB"
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$SB | python3 -c "
import json,sys,re; d=json.load(sys.stdin); s=json.dumps(d); print('keys:', sorted(d)[:30]); print('ips in API:', sorted(set(re.findall(r'\b\d+\.\d+\.\d+\.\d+\b', s))))"
echo "aenv-server network: $(sudo docker inspect aenv-server --format '{{.HostConfig.NetworkMode}}')"
echo "host addrs: $(ip -4 -o addr | awk '{print $2"="$4}' | grep -vE "^(lo|eno|enp|docker0|podman0)" | head -8 | tr '\n' ' ')"
$A exec $SB -- bash -c 'cat > /tmp/slow.py <<PY
import http.server, time
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(float(self.path.strip("/") or 0)); self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
http.server.ThreadingHTTPServer(("0.0.0.0", 7000), H).serve_forever()
PY
setsid nohup python3 /tmp/slow.py >/dev/null 2>&1 </dev/null &; ip -4 -o addr' 2>/dev/null | tail -3; sleep 2
for ip in $(sudo ss -tnp 2>/dev/null | grep -oE "10\.[0-9.]+|169\.254\.[0-9.]+|172\.[0-9.]+" | sort -u | head -0); do :; done
echo "$SB" > /tmp/aenv_direct_sb
