#!/bin/bash
# GRPO epochs 4-5 (epoch 3 is recorded): training on the 1-GPU pod (71zx..), rollouts served by the 2-GPU pod (o8dp..,
# vLLM data parallel, tunnel 06:8101) for speed. Recordings: live 16x8 cap-20, tfork, prefix (screen) cache warmed on
# the earlier epochs only. Replaces run_e45c.sh while pol5s was training (its training run is left as is).
cd /mnt/ssd2/vikranth/osworld
K=/home/vikranth/.ssh/runpod_wa
T="ssh -i $K -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"     # training pod
S="ssh -i $K -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -p 10590 root@103.207.149.118"    # serving pod
B=pod_backup/grpo_think_reg/adapters
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"

tunnel() {
  curl -s -m 5 http://127.0.0.1:8101/v1/models >/dev/null && return
  pkill -u vikranth -f "8101:127.0.0.1:8000"
  sudo -u vikranth ssh -f -N -i $K -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
    -L 8101:127.0.0.1:8000 -p 10590 root@103.207.149.118
}

wait_train() {  # $1 pod script name: wait for it to end on the training pod
  until $T "grep -q \"== done\|FAILED\" /root/${1%.sh}.log" 2>/dev/null; do sleep 30; done
  $T "grep -v \"Loading\|Fetching\" /root/${1%.sh}.log | tail -6"
  $T "grep -q FAILED /root/${1%.sh}.log" && { echo "training $1 FAILED, stopping"; exit 1; }
}

serve() {  # $1 adapter name, $2 served model name: adapter -> 06 backup -> serving pod, merge, serve on every GPU
  rsync -a -e "ssh -i $K -o StrictHostKeyChecking=no -p 19413" root@64.247.201.57:/root/adapters/grpo_think_reg/$1 $B/
  until $S "grep -q SETUP_DONE /root/dp_setup.log" 2>/dev/null; do sleep 20; done
  $S "mkdir -p /root/adapters"
  rsync -a -e "ssh -i $K -o StrictHostKeyChecking=no -p 10590" $B/$1 root@103.207.149.118:/root/adapters/
  $S "bash /root/dp_serve.sh /root/adapters/$1 $2" || { echo "serving $2 FAILED"; exit 1; }
  tunnel
  until curl -s -m 5 http://127.0.0.1:8101/v1/models | grep -q "$2"; do sleep 10; tunnel; done
  echo "serving $2 on the 2-GPU pod $(date +%T)"
}

train() {  # $1 trace dir, $2 pod data dir, $3 pod script
  echo "train $3 on $1 start $(date +%T)"
  rsync -a --include="*/" --include="chat.jsonl" --include="result.txt" --include="step_*.png" --exclude="*" \
    -e "ssh -i $K -o StrictHostKeyChecking=no -p 19413" "$1/" "root@64.247.201.57:/root/data/$2/" || { echo "rsync failed"; exit 1; }
  $T "nohup bash /root/$3 > /root/${3%.sh}.log 2>&1 < /dev/null &"
  wait_train $3
}

record() {  # $1 model, $2 result dir, $3 earlier epochs for the screen cache
  echo "record $2 with $1 start $(date +%T)"
  rm -rf "$2"
  env DOUBAO_API_URL=http://127.0.0.1:8101/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=1 \
    venv/bin/python osw_run.py --system tfork --spec off --model "$1" --tasks grpo16.json --rollouts 8 --max-steps 20 \
    --screen-cache 1 --screen-warm "$3" --result-dir "$2" $RUN > "$2.log" 2>&1
  echo "record $2 rc=$? $(date +%T)"
}

echo "pol5s training (started by run_e45c.sh) $(date +%T)"
wait_train train_e5_shot.sh
serve e5_shot grpo_think_reg-pol5s
record grpo_think_reg-pol5s traces/rec128e4_shot traces/rec128_shot,traces/rec128e2_shot,traces/rec128e3_shot
train traces/rec128e4_shot shot_reg_e5 train_e6_shot.sh
serve e6_shot grpo_think_reg-pol6s
record grpo_think_reg-pol6s traces/rec128e5_shot traces/rec128_shot,traces/rec128e2_shot,traces/rec128e3_shot,traces/rec128e4_shot
echo "rc=done"
