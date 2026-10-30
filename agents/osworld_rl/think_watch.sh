#!/bin/bash
# Live status of the Thinking GRPO runs on 06 (reg vs spec): ./think_watch.sh [seconds, default 30]. Ctrl-C to stop.
# One-shot: ./think_watch.sh once
show() {
  ssh -o ConnectTimeout=10 06 'cd /mnt/ssd2/vikranth/osworld && date "+%H:%M:%S on 06" && python3 think_status.py \
    && echo && echo "loop: $(grep -E "^epoch|rc=|SKIP|STOP" traces/run_think_2x2.log | tail -3 | cut -c1-160 | tr "\n" ";")" \
    && echo "tmux: $(sudo tmux ls 2>&1 | cut -d: -f1 | tr "\n" " ")  load: $(cut -d" " -f1-3 /proc/loadavg)  ssd2 free: $(df -h --output=avail /mnt/ssd2 | tail -1)"' 2>&1
}
[ "$1" = once ] && { show; exit; }
while true; do out=$(show); clear; echo "$out"; sleep "${1:-30}"; done
