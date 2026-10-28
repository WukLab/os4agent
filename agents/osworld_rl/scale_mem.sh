#!/bin/bash
# Peak memory vs. concurrent rollouts: batch size B x 8 rollouts, every copy alive at once, tfork vs. CRIU.
#   ./scale_mem.sh [out-dir]                      default traces/scale
#   SIZES="8 16 32 64 128 256" SYSTEMS="tfork criu" LIMIT_GIB=450 REPLAY_LATENCY=0 BASE_FORK=0 ./scale_mem.sh
# BASE_FORK=1 boots one desktop and forks it into every task's source instead of booting each source.
# Each point replays traces/rec32v2_tfork with --groups B, taking the first B tasks of one fixed shuffled order (seed
# 1), so every size contains the smaller ones' tasks; the 32 recorded tasks repeat when B > 32. A run stops when
# host used memory passes LIMIT_GIB; that system then skips its larger sizes. Finished points are skipped, so the
# script can be rerun after an interruption. The CSV and plot in <out-dir> are refreshed after every run.
set -u
cd "$(dirname "$0")"
OUT=${1:-traces/scale}
SIZES=${SIZES:-"8 16 32 64 128 256"}
SYSTEMS=${SYSTEMS:-"tfork criu"}
LIMIT_GIB=${LIMIT_GIB:-450}
BASE_FORK=${BASE_FORK:-0}
REPLAY_LATENCY=${REPLAY_LATENCY:-0}  # actions back to back; peak memory depends on which actions run, not their pace
REC=${REC:-traces/rec32v2_tfork}
TASKS=${TASKS:-grpo_batch32v2.json}
OS4AGENT=${OS4AGENT:-/mnt/ssd2/os4agent}
STORAGE_CONF=${STORAGE_CONF:-/mnt/btrfs/podman/storage.conf}
P="sudo env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=$STORAGE_CONF CONTAINERS_CONF=$PWD/containers-os4agent.conf $OS4AGENT/podman-tfork.sh"
mkdir -p "$OUT"
cat > "$OUT/sweep.txt" <<END
started $(date -Is) on $(hostname)
sizes=$SIZES systems=$SYSTEMS limit_gib=$LIMIT_GIB replay=$REC tasks=$TASKS replay_latency=$REPLAY_LATENCY base_fork=$BASE_FORK
8 rollouts per group; all groups fork, roll out and tear down together; setup concurrency 16, fork concurrency 4
END

for sys in $SYSTEMS; do
  for n in $SIZES; do
    if [ -e "$OUT/$sys.oom" ]; then
      echo "$(date +%T) $sys n=$n skipped: hit the memory limit at n=$(cat "$OUT/$sys.oom")"
      continue
    fi
    for seed in 1; do  # one fixed task order for every size
      dir="$OUT/${sys}_n${n}_s${seed}"
      if grep -q '"run_done"' "$dir/events.jsonl" 2>/dev/null; then
        echo "$(date +%T) $dir done already"
      else
        sudo rm -rf "$dir"
        echo "$(date +%T) $dir: $((n / 8)) groups x 8"
        sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system "$sys" --tasks "$TASKS" \
          --replay "$REC" --replay-latency "$REPLAY_LATENCY" --groups $((n / 8)) --rollouts 8 --shuffle-seed "$seed" --sync-groups 1 --base-fork "$BASE_FORK" \
          --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib "$LIMIT_GIB" \
          --os4agent "$OS4AGENT" --storage-conf "$STORAGE_CONF" --result-dir "$dir" > "$dir.log" 2>&1
        $P ps -aq | xargs -r -n 50 $P rm -f > /dev/null 2>&1  # anything a crashed run left behind
        sudo chown -R "$(id -u):$(id -g)" "$dir" "$dir.log"
        venv/bin/python scale_plot.py "$OUT" > /dev/null 2>&1 || echo "plot failed"
      fi
      if grep -q '"mem_limit"' "$dir/events.jsonl" 2>/dev/null; then
        echo "$n" > "$OUT/$sys.oom"
        echo "$(date +%T) $sys hit the memory limit at n=$n"
        break
      fi
    done
  done
done
echo "$(date +%T) sweep done; plot with: python3 scale_plot.py $OUT"
