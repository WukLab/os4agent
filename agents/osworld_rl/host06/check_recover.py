"""Run osw_run.py's real Podman.recover_source on container lk-test (locked + frozen by the caller)."""
import ast, json, re, subprocess, sys
src = open("osw_run.py").read()
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Podman")
fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "recover_source")
events = []
g = {"re": re, "subprocess": subprocess, "log": lambda ev, **kw: events.append((ev, kw))}
exec(compile(ast.Module([fn], []), "osw_run.py", "exec"), g)
P = sys.argv[1:]
class Stub:
    def p(self, *args, check=True):
        return subprocess.run(P + list(args), capture_output=True, text=True)
g["recover_source"](Stub(), "lk-test", task="check")
print("events:", events)
