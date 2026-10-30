#!/bin/bash
# Copy each new adapter (e5_shot = pol5s, e6_shot = pol6s) and the training logs from the pod to 06 as soon as it is saved.
B=/mnt/ssd2/vikranth/osworld/pod_backup/grpo_think_reg
SSH="ssh -i /home/vikranth/.ssh/runpod_wa -o StrictHostKeyChecking=no -p 19413"
for a in e5_shot e6_shot; do
  until $SSH root@64.247.201.57 "test -f /root/adapters/grpo_think_reg/$a/train_stats.json" 2>/dev/null; do sleep 60; done
  rsync -a -e "$SSH" root@64.247.201.57:/root/adapters/grpo_think_reg/$a $B/adapters/
  rsync -a -e "$SSH" --include="train_*.log" --include="train_*.sh" --exclude="*" root@64.247.201.57:/root/ $B/logs/
  echo "backed up $a $(date +%T)"
done
