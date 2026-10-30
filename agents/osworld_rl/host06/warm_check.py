"""How many epoch-2 steps the screen cache could serve from each warm source (offline, no desktops).
python warm_check.py CUR_TRACE WARM_DIR [WARM_DIR ...]"""
import glob, importlib.util, json, os, sys
cur, warm = sys.argv[1], sys.argv[2:]
sys.argv = ["osw_run.py", "--system", "tfork", "--tasks", "grpo16.json", "--screen-cache", "1",
            "--result-dir", "/tmp/vk_sc/x", "--model", "replay"]
spec = importlib.util.spec_from_file_location("osr", "/mnt/ssd2/vikranth/osworld/osw_run.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
for label, dirs in [("epoch 1 only", [w for w in warm if w.endswith("rec128_shot")]), ("all earlier traces", warm)]:
    m.SCACHE.d.clear()
    n_e = m.SCACHE.warm(dirs)
    hits = n = right = 0
    for d in glob.glob(f"{cur}/*/*__g*"):
        ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        task = os.path.basename(d).split("__g")[0]
        for j in range(min(len(ch), len(tr)) - 1):
            k, t = m.action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit")), m.screen_text(ch[j])
            if k is None or t is None:
                continue
            n += 1
            if e := m.SCACHE.get(task, t, k):
                hits += 1
                nt = m.screen_text(ch[j + 1])
                right += nt is not None and m.CLOCK.sub("", nt) == m.CLOCK.sub("", e[0])
    print(f"{label}: {n_e} entries; epoch-2 steps {n}: hits {hits} ({hits / n:.0%}), right {right} ({right / n:.0%} of steps)")
