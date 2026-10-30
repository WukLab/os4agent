"""Run osw_run.py's real keep_failed_clone on a fake failed clone-of-clone bundle; the linked snapshot must survive."""
import ast, glob, os, pathlib, re, shutil, subprocess, tempfile
src = open("osw_run.py").read()
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "keep_failed_clone")
root = pathlib.Path(tempfile.mkdtemp(prefix="vk_kfc_"))
g = {"os": os, "re": re, "glob": glob, "shutil": shutil, "subprocess": subprocess, "OUT": root / "out"}
exec(compile(ast.Module([fn], []), "osw_run.py", "exec"), g)
R = root / "group_snapshot"; R.mkdir(); (R / "file").write_text("x")            # stands in for the group's snap-ro
b = root / "tfork-bundles" / ("ab" * 32); b.mkdir(parents=True)
(b / "crun-tfork.log").write_text("Error (criu/cr-dump.c:1): tfork FAILED\n")
os.symlink(R, b / "snap-ro")                                                    # what a failed clone of a clone leaves
errs = g["keep_failed_clone"](f"... {b}/crun-tfork.log ...")
print("errors returned:", errs)
print("failed bundle removed:", not b.exists(), "| logs kept:", sorted(os.listdir(root / "out" / "failed_clones")))
print("group snapshot survives:", R.is_dir() and (R / "file").exists())
assert not b.exists() and R.is_dir() and (R / "file").exists()
shutil.rmtree(root)
print("PASS")
