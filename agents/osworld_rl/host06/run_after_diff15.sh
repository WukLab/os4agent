#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=diff15" 2>/dev/null; do sleep 10; done
bash run_stop15.sh
