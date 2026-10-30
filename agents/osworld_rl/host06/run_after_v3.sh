#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=shot6v3" 2>/dev/null; do sleep 10; done
bash run_shot6v4.sh
