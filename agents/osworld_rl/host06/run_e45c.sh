#!/bin/bash
# GRPO epochs 3-5, live 16x8 cap-20 recordings on tfork; epochs 4-5 with the prefix (screen) cache warmed on the earlier epochs only, one LoRA update
# between epochs on the pod. Waits for the epoch-3 recording already running (run_e3.sh, pol4s), then:
#   train pol5s on epoch 3 -> record epoch 4 -> train pol6s on epoch 4 -> record epoch 5.
cd /mnt/ssd2/vikranth/osworld
POD="ssh -i /home/vikranth/.ssh/runpod_wa -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"

train() {  # $1 trace dir, $2 pod data dir name, $3 pod script, $4 model it serves when done
  echo "train $3 on $1 start $(date +%T)"
  rsync -a --include="*/" --include="chat.jsonl" --include="result.txt" --include="step_*.png" --exclude="*" \
    -e "ssh -i /home/vikranth/.ssh/runpod_wa -o StrictHostKeyChecking=no -p 19413" "$1/" "root@64.247.201.57:/root/data/$2/" || { echo "rsync failed"; exit 1; }
  $POD "nohup bash /root/$3 > /root/${3%.sh}.log 2>&1 < /dev/null &"
  until $POD "grep -q \"== done\|FAILED\" /root/${3%.sh}.log" 2>/dev/null; do sleep 60; done
  $POD "grep -v \"Loading\|Fetching\" /root/${3%.sh}.log | tail -8"
  $POD "grep -q FAILED /root/${3%.sh}.log" && { echo "training $3 FAILED, stopping"; exit 1; }
  until curl -s -m 5 http://127.0.0.1:8100/v1/models | grep -q "$4"; do sleep 20; done
  echo "train $3 done, serving $4 $(date +%T)"
}

record() {  # $1 model, $2 result dir, $3 earlier epochs for the screen cache
  echo "record $2 with $1 start $(date +%T)"
  rm -rf "$2"
  env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=1 \
    venv/bin/python osw_run.py --system tfork --spec off --model "$1" --tasks grpo16.json --rollouts 8 --max-steps 20 \
    --screen-cache 1 --screen-warm "$3" --result-dir "$2" $RUN > "$2.log" 2>&1
  echo "record $2 rc=$? $(date +%T)"
}

until grep -q "^rc=done" traces/run_e3.out 2>/dev/null; do sleep 30; done
echo "epoch 3 recorded $(date +%T)"
train traces/rec128e3_shot shot_reg_e4 train_e5_shot.sh grpo_think_reg-pol5s
record grpo_think_reg-pol5s traces/rec128e4_shot traces/rec128_shot,traces/rec128e2_shot,traces/rec128e3_shot
train traces/rec128e4_shot shot_reg_e5 train_e6_shot.sh grpo_think_reg-pol6s
record grpo_think_reg-pol6s traces/rec128e5_shot traces/rec128_shot,traces/rec128e2_shot,traces/rec128e3_shot,traces/rec128e4_shot
echo "rc=done"
