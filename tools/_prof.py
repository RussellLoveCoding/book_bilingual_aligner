import sys, time
sys.path.insert(0, '.')
sys.path.insert(0, '..')
from bil import epubparse as E, structure as S, align as A

def t(label, fn):
    t0 = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t0
    print(f"  {label:34s} {dt:7.2f}s")
    return r

for label, en, zh in [('think2 (3.6MB)', '../.workbuddy/tmp/books/think2_en.epub',
                       '../.workbuddy/tmp/books/think2_zh.epub'),
                      ('prob (17MB, 最慢)', '../.workbuddy/tmp/books/prob_en.epub',
                       '../.workbuddy/tmp/books/prob_zh.md')]:
    print(f"=== {label} ===")
    ze = t('打开英文 epub', lambda: E.open_epub(en))
    zz = t('打开中文输入', lambda: E.open_epub(zh) if zh.endswith('.epub') else None)
    sp_e = t('读 spine', lambda: E.read_spine(ze))
    t('加载+解析英文文档', lambda: S.load_docs(ze, sp_e))
    if zz:
        sp_z = t('读 spine(中)', lambda: E.read_spine(zz))
        t('加载+解析中文文档', lambda: S.load_docs(zz, sp_z))
    print()
