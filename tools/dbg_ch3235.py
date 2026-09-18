# -*- coding: utf-8 -*-
"""确认 ch32/ch35 那两篇「零中文」是不是 Bibliography / Index（本就未译）。"""
import sys
from pathlib import Path
_H = Path(__file__).resolve().parent
sys.path.insert(0, str(_H)); sys.path.insert(0, str(_H.parent))
from bil import epubparse as E, structure as S
from bil import bookscan_chk as BC  # noqa
