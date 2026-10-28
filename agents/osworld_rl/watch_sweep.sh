#!/bin/bash
# Watch a scale_mem.sh sweep on the env host from your laptop. Refreshes every 30 s; Ctrl-C to stop.
# Also copies the latest CSV and plot to ./results/<sweep>/ (open the PNG in Preview; it reloads on change).
#   ./watch_sweep.sh [sweep-name] [host] [tmux-session]     default motivation_1_peak_memory on 06, session motivation1
SWEEP=${1:-motivation_1_peak_memory}
HOST=${2:-06}
SESSION=${3:-motivation1}
DIR=/mnt/ssd2/vikranth/osworld
LOCAL=$(cd "$(dirname "$0")" && pwd)/results/$SWEEP
mkdir -p "$LOCAL"
while true; do
  out=$(ssh -o ConnectTimeout=10 "$HOST" "cd $DIR &&
    printf '  %s   tmux %s   host memory used %s of %s GiB\n\n' \"\$(hostname)\" \
      \"\$(tmux has-session -t $SESSION 2>/dev/null && echo running || echo STOPPED)\" \
      \"\$(free -g | awk '/^Mem/ {print \$3}')\" \"\$(free -g | awk '/^Mem/ {print \$2}')\" &&
    python3 scale_check.py traces/$SWEEP" 2>&1)
  rsync -q "$HOST:$DIR/traces/$SWEEP/scale.*" "$LOCAL/" 2>/dev/null
  clear
  printf '\n%s\n\n  plot and CSV: %s/scale.png   (refreshes every 30 s, Ctrl-C to stop)\n' "$out" "$LOCAL"
  sleep 30
done
