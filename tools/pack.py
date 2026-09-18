"""把整条流水线打包成单个可执行文件。

两种产物，按需选一种：

  1) .pyz（推荐，纯 Python，无需编译）
     python tools/pack.py --zipapp
     → dist/bilingual-epub.pyz
     运行：python dist/bilingual-epub.pyz --help
           python dist/bilingual-epub.pyz web        # 起网页版

  2) .exe（Windows 单文件，PyInstaller）
     python tools/pack.py --exe
     → dist/bilingual-epub.exe
     需要先装 PyInstaller：pip install pyinstaller

.zipapp 走标准库 zipapp，零依赖；把 tools/bil、run_book.py、app.py 全塞进
一个压缩包，Python 解释器直接能跑。用户只拿到一个文件。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipapp
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
DIST = ROOT / "dist"

# zipapp 的入口：先按 sys.argv[1] 路由到 web 或 cli
ENTRY = '''\
"""双语电子书流水线 · 单文件入口。

  python bilingual-epub.pyz web [--port 8765]    # 本地网页版
  python bilingual-epub.pyz cli --all --build    # 命令行
  python bilingual-epub.pyz --help
"""
import sys, os
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _ensure_importable():
    """zipapp 里包内模块需要能互相 import，且工作目录要能放 .env / build。"""
    p = str(_HERE)
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    _ensure_importable()
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("子命令：")
        print("  web [--port N] [--no-browser]   启动本地网页版")
        print("  cli <run_book.py 的参数>        命令行模式")
        print("  probe                           结构体检")
        return
    cmd, rest = args[0], args[1:]
    if cmd == "web":
        import app
        sys.argv = ["app"] + rest
        app.main()
    elif cmd == "cli":
        import run_book
        sys.argv = ["run_book"] + rest
        run_book.main()
    elif cmd == "probe":
        import probe_book
        sys.argv = ["probe_book"] + rest
        probe_book.main()
    else:                       # 没给子命令时，把参数直接当 cli 参数
        import run_book
        sys.argv = ["run_book"] + args
        run_book.main()


if __name__ == "__main__":
    main()
'''


def build_zipapp(out: Path) -> None:
    """用 zipapp 打一个纯 Python 单文件。"""
    stage = DIST / "_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # tools/bil → 包目录
    shutil.copytree(_HERE / "bil", stage / "bil",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in ("run_book.py", "probe_book.py", "app.py"):
        shutil.copy2(_HERE / f, stage / f)
    (stage / "__main__.py").write_text(ENTRY, encoding="utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    zipapp.create_archive(stage, target=out, interpreter="/usr/bin/env python3",
                          compressed=True)
    shutil.rmtree(stage)

    size = out.stat().st_size / 1024
    print(f"\n  已生成 {out}  （{size:.0f} KB）")
    print(f"  运行：")
    print(f"    python {out.name} web            # 网页版")
    print(f"    python {out.name} cli --all --build")
    print(f"    python {out.name} probe")


def build_exe(out: Path) -> None:
    """用 PyInstaller 打 Windows 单文件 exe。"""
    if shutil.which("pyinstaller") is None:
        print("  [!] 未找到 pyinstaller。")
        print("      安装：pip install pyinstaller")
        print("      或改用 --zipapp（零依赖，同样是一个文件）")
        return
    work = DIST / "_build"
    work.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pyinstaller", "--noconfirm", "--clean", "--onefile",
        "--name", "bilingual-epub",
        "--distpath", str(DIST), "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(_HERE),
        "--hidden-import", "bil",
        str(_HERE / "app.py"),
    ]
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=False)
    exe = DIST / ("bilingual-epub.exe" if os.name == "nt" else "bilingual-epub")
    if exe.exists():
        print(f"\n  已生成 {exe}  （{exe.stat().st_size / 1048576:.1f} MB）")
        print(f"  双击即可启动网页版；也可在命令行加 cli 参数走 CLI。")
    else:
        print("\n  [!] PyInstaller 未产出文件，请检查上面的报错。")


def main() -> None:
    ap = argparse.ArgumentParser(description="打包双语电子书流水线为单个文件")
    ap.add_argument("--zipapp", action="store_true",
                    help="打 .pyz（纯 Python，零依赖，推荐）")
    ap.add_argument("--exe", action="store_true",
                    help="打 Windows .exe（需 PyInstaller）")
    ap.add_argument("--out", default="", help="输出文件名（可选）")
    args = ap.parse_args()

    if not args.zipapp and not args.exe:
        args.zipapp = True                       # 默认走 zipapp

    if args.zipapp:
        out = DIST / (args.out or "bilingual-epub.pyz")
        build_zipapp(out)
    if args.exe:
        build_exe(DIST)


if __name__ == "__main__":
    main()
