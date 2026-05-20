"""
theme.py - PinkLAB 디자인 토큰
================================

색상, 폰트, 레이아웃 상수 중앙 관리.
디자인 변경 시 이 파일만 수정하면 전체 게임 적용.

Author: Stephen (gjkong)
Date: 2026-04-30
"""

# ============================================================
# 1. 색상 팔레트 (BGR 형식 - OpenCV 기준)
# ============================================================
# OpenCV는 BGR 순서. PIL은 RGB. 변환은 ui_renderer에서 처리.

# PinkLAB 메인 컬러 (RGB)
PINKLAB_PINK = (157, 107, 255)      # #FF6B9D - 메인 핑크
PINKLAB_PINK_DARK = (107, 60, 200)  # 어두운 핑크
PINKLAB_PINK_LIGHT = (220, 180, 255)  # 밝은 핑크 (강조)

# 게임 결과 색상
COLOR_WIN = (76, 175, 80)        # 초록 (#4CAF50)
COLOR_LOSE = (54, 67, 244)       # 빨강 (BGR이라 R=244)
COLOR_DRAW = (7, 193, 255)       # 노랑 (#FFC107)

# AI vs 사용자
COLOR_AI = (235, 152, 33)        # 블루 (#2196F3 BGR)
COLOR_USER = PINKLAB_PINK        # 핑크

# 기본 색상
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GRAY_LIGHT = (200, 200, 200)
COLOR_GRAY_MID = (130, 130, 130)
COLOR_GRAY_DARK = (50, 50, 50)

# 배경 (반투명 패널용)
COLOR_PANEL_BG = (30, 30, 40)


# ============================================================
# 2. 화면 레이아웃
# ============================================================
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480

# 화면 표시 확대 배율 (카메라 입력은 그대로, 보여주는 것만 확대)
# 1.0 = 640x480 (작음)
# 1.5 = 960x720 (적당) ⭐ 추천
# 2.0 = 1280x960 (큼)
# 2.5 = 1600x1200 (매우 큼)
DISPLAY_SCALE = 1.5

# 영역 분할 (높이 비율) - 480 기준 재계산
HEADER_HEIGHT = 60       # 상단 점수/난이도 패널
AI_AREA_HEIGHT = 150     # 중상단 AI 영역
MESSAGE_AREA_HEIGHT = 40 # 중앙 메시지 영역
USER_AREA_HEIGHT = (SCREEN_HEIGHT - HEADER_HEIGHT 
                    - AI_AREA_HEIGHT - MESSAGE_AREA_HEIGHT)

# 영역별 시작 y 좌표
HEADER_Y = 0
AI_AREA_Y = HEADER_HEIGHT
MESSAGE_AREA_Y = HEADER_HEIGHT + AI_AREA_HEIGHT
USER_AREA_Y = MESSAGE_AREA_Y + MESSAGE_AREA_HEIGHT


# ============================================================
# 3. 폰트 크기 (640x480 기준 축소)
# ============================================================
FONT_SIZE_HUGE = 50      # 카운트다운, 결과
FONT_SIZE_LARGE = 32     # 손 모양 표시
FONT_SIZE_MEDIUM = 22    # 메시지
FONT_SIZE_NORMAL = 18    # 일반 텍스트
FONT_SIZE_SMALL = 14     # 보조 정보


# ============================================================
# 4. 손 모양 한글/이모지 매핑
# ============================================================
SHAPE_KOREAN = {
    "rock": "바위",
    "scissors": "가위",
    "paper": "보",
    "gun": "총",
    "phoenix": "불사조",
    "unknown": "??",
}

SHAPE_EMOJI = {
    "rock": "✊",
    "scissors": "✌️",
    "paper": "🖐️",
    "gun": "👉",
    "phoenix": "🤟",
    "unknown": "❓",
}

SHAPE_KOREAN_FULL = {
    "rock": "바위 ✊",
    "scissors": "가위 ✌️",
    "paper": "보 🖐️",
    "gun": "총 👉",
    "phoenix": "불사조 🤟",
    "unknown": "??",
}


# ============================================================
# 5. 난이도 한글
# ============================================================
DIFFICULTY_KOREAN = {
    "easy": "쉬움",
    "normal": "보통",
    "hard": "어려움",
}

DIFFICULTY_COLOR = {
    "easy": COLOR_WIN,           # 초록
    "normal": COLOR_DRAW,        # 노랑
    "hard": COLOR_LOSE,          # 빨강
}


# ============================================================
# 6. 게임 타이밍 (초)
# ============================================================
TIMING_COUNTDOWN = 3.0     # 3-2-1
TIMING_DETECTION = 1.5     # 손 모양 인식
TIMING_REVEAL = 0.8        # AI 손 공개 딜레이
TIMING_ROUND_RESULT = 2.0  # 라운드 결과 표시


# ============================================================
# 7. 사운드 파일 경로
# ============================================================
SOUND_FILES = {
    "countdown": "countdown.wav",
    "reveal": "reveal.wav",
    "win": "win.wav",
    "lose": "lose.wav",
    "victory": "victory.wav",
    "click": "click.wav",
}
