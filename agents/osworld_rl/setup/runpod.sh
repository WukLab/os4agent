#!/bin/bash
# RunPod GPU pod for the model server and trainer, via the REST API. Needs RUNPOD_API_KEY in the environment.
#   setup/runpod.sh create <name> <pubkey-file>...   one A100 80GB, runpod/pytorch CUDA 12.8 image, 200 GB disk, ssh only
#   setup/runpod.sh info|start|stop <pod-id>          info prints the ssh command (the port changes on every start)
# The pod has no volume: stopping it keeps the disk, but RunPod may move a stopped pod and wipe it; rerun pod_serve.sh then.
set -euo pipefail
: "${RUNPOD_API_KEY:?set RUNPOD_API_KEY}"
API=https://rest.runpod.io/v1/pods
call() { curl -fsS -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" "$@"; }

case ${1:-} in
create)
  name=$2; shift 2
  keys=$(cat "$@")  # every public key that should get ssh access (laptop + env host)
  body=$(KEYS="$keys" NAME="$name" python3 -c 'import json, os; print(json.dumps({
      "name": os.environ["NAME"], "imageName": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
      "gpuTypeIds": ["NVIDIA A100-SXM4-80GB", "NVIDIA A100 80GB PCIe"], "gpuCount": 1,
      "containerDiskInGb": 200, "volumeInGb": 0, "ports": ["22/tcp"], "cloudType": "SECURE",
      "env": {"PUBLIC_KEY": os.environ["KEYS"]}}))')
  call -X POST "$API" -d "$body" | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])' ;;
start|stop)
  call -X POST "$API/$2/$1" >/dev/null && echo "$1 requested" ;;
info)
  call "$API/$2" | python3 -c 'import json, sys; p = json.load(sys.stdin)
port = (p.get("portMappings") or {}).get("22")
print(p.get("desiredStatus"), (p.get("machine") or {}).get("gpuDisplayName", ""))
ip = p.get("publicIp")
print(f"ssh -p {port} root@{ip}" if port else "no ssh port yet (pod not running)")' ;;
*) sed -n 2,5p "$0"; exit 1 ;;
esac
