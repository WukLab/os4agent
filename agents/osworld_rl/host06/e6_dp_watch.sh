#!/bin/bash
# On 06: once epoch 4 is recorded (run_e45d.sh), train pol6s on the 2-GPU pod with data parallelism and push the adapter
# to the training pod, where run_e45d.sh's train step (a stub) is waiting for it. On failure: fall back to the old path.
cd /mnt/ssd2/vikranth/osworld
K=/home/vikranth/.ssh/runpod_wa
T="ssh -i $K -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"
S="ssh -i $K -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -p 10590 root@103.207.149.118"
B=pod_backup/grpo_think_reg/adapters
until grep -q "record traces/rec128e4_shot rc=" traces/run_e45d.out; do sleep 10; done
echo "epoch 4 recorded, training pol6s on the 2-GPU pod $(date +%T)"
fail() { echo "FAILED: $1, falling back to the training pod $(date +%T)"; $T "touch /root/e6_fallback"; exit 1; }
rsync -a --include="*/" --include="chat.jsonl" --include="result.txt" --include="step_*.png" --exclude="*" \
  -e "ssh -i $K -o StrictHostKeyChecking=no -p 10590" traces/rec128e4_shot/ root@103.207.149.118:/root/data/shot_reg_e5/ || fail "data copy"
$S "test -f /root/adapters/e5_shot/adapter_config.json" || fail "no e5_shot on the 2-GPU pod"
$S "bash /root/train_dp.sh /root/data/shot_reg_e5 /root/adapters/e5_shot /root/adapters/e6_shot > /root/train_dp_e6.log 2>&1" || fail "training"
$S "grep -v 'Loading\|Fetching' /root/train_dp_e6.log | tail -8"
$S "test -f /root/adapters/e6_shot/train_stats.json && test -f /root/merged/e6_shot/config.json" || fail "no adapter or merge"
rsync -a -e "ssh -i $K -o StrictHostKeyChecking=no -p 10590" root@103.207.149.118:/root/adapters/e6_shot $B/ || fail "adapter copy back"
rsync -a -e "ssh -i $K -o StrictHostKeyChecking=no -p 10590" root@103.207.149.118:/root/train_dp_e6.log pod_backup/grpo_think_reg/logs/
$T "mkdir -p /root/adapters/grpo_think_reg/e6_shot.tmp" && rsync -a -e "ssh -i $K -o StrictHostKeyChecking=no -p 19413" $B/e6_shot/ root@64.247.201.57:/root/adapters/grpo_think_reg/e6_shot.tmp/ \
  && $T "mv /root/adapters/grpo_think_reg/e6_shot.tmp /root/adapters/grpo_think_reg/e6_shot" || fail "push to the training pod"
echo "pol6s pushed $(date +%T)"
