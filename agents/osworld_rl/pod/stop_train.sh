#!/bin/bash
# on the pod: stop a running train_grpo.py (not needed when only rollouts are compared)
pgrep -f "osworld_rl/train_grpo.py|python train_grpo.py" | xargs -r kill; sleep 3; echo "train processes left: $(pgrep -fc "train_grpo.py --base")"
