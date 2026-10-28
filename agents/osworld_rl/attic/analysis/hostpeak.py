import json
for r in ("replay32_tfork_overlay", "replay32_tfork"):
    rows = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{r}/mem.jsonl")]
    base = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{r}/events.jsonl")][1]
    pk = max(rows, key=lambda x: x["host"]["used_delta_mib"]); pp = max(rows, key=lambda x: x["total"]["pss_mib"])
    for name, x in (("at host peak", pk), ("at PSS peak", pp)):
        t, h = x["total"], x["host"]
        print(f"{r:24s} {name:12s} host_used_delta {h['used_delta_mib']/1024:5.1f}  PSS {t['pss_mib']/1024:5.1f}  cgroup {t['cg_mib']/1024:5.1f} "
              f"(anon {t['cg_anon_mib']/1024:4.1f} file {t['cg_file_mib']/1024:4.1f} kernel {t['cg_kernel_mib']/1024:4.1f} shmem {t['cg_shmem_mib']/1024:4.1f})  "
              f"host anon {h['anon_mib']/1024:5.1f} shmem {h['shmem_mib']/1024:4.1f} cached {h['cached_mib']/1024:5.1f}  envs {len(x['containers'])}")
    print("   run-start host:", base.get("host_baseline"))
