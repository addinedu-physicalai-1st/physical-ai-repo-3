"""
W7 단위 테스트 conftest
=========================

폴더명이 숫자로 시작(`08_zombie_dodge`)해서 일반 import 불가.
src/ 경로를 sys.path에 주입.
W2~W6과 동일 패턴.

NOTE: tests/__init__.py 만들지 않음 (W3 트러블 #12).
"""

import os
import sys

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src")
)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
