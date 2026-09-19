"""极简测试跑手（本机无 pytest）。用法：python tests/_runtests.py <测试文件...>"""
import sys
import importlib.util
import pathlib

sys.stdout.reconfigure(encoding="utf-8")


def run(path: str) -> tuple[int, int]:
    p = pathlib.Path(path)
    spec = importlib.util.spec_from_file_location("t_" + p.stem, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    fns = [(n, f) for n, f in vars(m).items() if n.startswith("test_") and callable(f)]
    ok = fail = 0
    print(f"\n=== {p.name} ===")
    for n, f in fns:
        try:
            f()
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  FAIL {n} -> {repr(e)[:300]}")
    print(f"  {ok} passed, {fail} failed (共 {len(fns)})")
    return ok, fail


if __name__ == "__main__":
    T = F = 0
    for arg in sys.argv[1:]:
        o, f = run(arg)
        T += o
        F += f
    print(f"\n合计 {T} passed, {F} failed")
    sys.exit(1 if F else 0)
