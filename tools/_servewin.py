"""Windows 侧起服务（用户验收用）。前台运行，日志直接落盘。"""
import sys, os
sys.path.insert(0, r"C:/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools")
os.chdir(r"C:/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools")
import app
from http.server import ThreadingHTTPServer
srv = ThreadingHTTPServer(("127.0.0.1", 8765), app.Handler)
print("bilingual app up on http://127.0.0.1:8765", flush=True)
srv.serve_forever()
