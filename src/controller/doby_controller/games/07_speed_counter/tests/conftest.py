"""
W2 단위 테스트 conftest
========================

폴더명이 숫자로 시작(`07_speed_counter`)해서 일반 패키지 import 불가.
src/ 경로를 sys.path에 주입해 `from question_gen import ...` 가능하게 함.
"""

import os
import sys

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src")
)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
