#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=lo3" 2>/dev/null; do sleep 10; done
bash run_diff15.sh
