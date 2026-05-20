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
    # W3 신규: slice = swish 효과음 (Downloads/swish.mp3 첫 swish 0.4초 추출)
    "slice": "slice.wav",
    # explosion 전용 wav는 미준비 → game.py에서 "lose" 매핑 재사용
}


# ============================================================
# 8. W3 카페 닌자 - 메뉴 객체 색상/이름 토큰
# ============================================================
# Sprite PNG가 없을 때 OpenCV 도형 placeholder의 색상 (BGR)
KIND_COLORS = {
    "americano":  (60, 80, 130),     # 진한 갈색
    "latte":      (180, 215, 240),   # 베이지/크림
    "cappuccino": (110, 145, 200),   # 카푸치노 갈색
    "cake":       (180, 195, 240),   # 케이크 핑크 (PinkLAB 톤)
    "croissant":  (110, 175, 230),   # 크루아상 황금색
    "kunai":      (160, 160, 170),   # 표창 — 메탈 회색 (placeholder, PNG 우선)
    "bomb":       (40, 40, 200),     # 빨강 (BGR이라 R=200)
}

KIND_KOREAN = {
    "americano":  "아메리카노",
    "latte":      "라떼",
    "cappuccino": "카푸치노",
    "cake":       "케이크",
    "croissant":  "크루아상",
    "kunai":      "표창",
    "bomb":       "폭탄",
}

KIND_LABEL = {
    "americano":  "AME",
    "latte":      "LAT",
    "cappuccino": "CAP",
    "cake":       "CAKE",
    "croissant":  "CROI",
    "kunai":      "KUNAI",
    "bomb":       "X",
}


# ============================================================
# 9. W3 폴리싱 - 닌자 마스코트 + 배경 에셋 경로
# ============================================================
import os as _os
_GAME_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
NINJA_SPRITE_DIR = _os.path.join(_GAME_ROOT, "assets", "images", "ninja")
NINJA_KUNAI_PATH = _os.path.join(NINJA_SPRITE_DIR, "kunai.png")
BACKGROUND_PATH = _os.path.join(_GAME_ROOT, "assets", "images", "background", "town.jpg")

# 마스코트 렌더 파라미터
MASCOT_HEIGHT = 180             # 리사이즈 후 픽셀 높이
MASCOT_FPS = 12
MASCOT_MARGIN_X = 8             # 좌측 마진
MASCOT_OFFSET_Y = HEADER_HEIGHT + 4  # 점수 패널 바로 아래

# 배경 블렌딩 강도 (0.0 = 카메라만, 1.0 = 배경만) — silhouette 비활성 시 폴백용
BACKGROUND_ALPHA = 0.40
# 배경 이미지 자체의 밝기 곱 (1.0 = 원본, 0.5 = 절반 밝기)
BACKGROUND_BRIGHTNESS = 0.85
# 배경 채도 곱 (1.0 = 원본, 1.5 = 채도 50% 상향)
BACKGROUND_SATURATION = 1.4

# 10. W3 폴리싱 - 닌자 복면 (2026-05-18 silhouette design)
# 사람 = 카메라 그대로 노출, 배경 = town.jpg, **코 위쪽 가로 ~ 턱 아래** 역삼각형 검정 마스크
MASK_COVER_TINT_BGR = (0, 0, 0)           # 검정 (닌자 마스크 정통 색)
MASK_COVER_ALPHA = 1.0                    # 1.0=평면 가림, 0.85=얼굴 약간 비침
# 역삼각형 꼭짓점 위치 (nose/mouth keypoint + eye 간격 기준)
MASK_COVER_TOP_WIDTH_RATIO = 1.7          # 위 변 가로 반폭 = 양 눈 거리 * 이 값 (크게)
MASK_COVER_TOP_Y_OFFSET_RATIO = -0.7      # 위 변 Y = nose_y + (nm_dist * 이 값)  (눈 아래 부근)
MASK_COVER_BOTTOM_Y_OFFSET_RATIO = 4.0    # 아래 꼭짓점 Y = mouth_y + (nm_dist * 이 값) (목 아래까지)
MASK_COVER_FEATHER = 0                    # 0=hard edge (번짐 없음, 마스크 답게)
MASK_COVER_BORDER_THICKNESS = 6           # 외곽 굵은 선 두께 (px). 0이면 외곽선 없음.
PERSON_MASK_THRESHOLD = 0.5               # Selfie Seg 확률 → 이진화 임계

# Legacy (silhouette mode 폴백용 — 손/눈 reveal 시나리오는 더 이상 사용 X)
SILHOUETTE_TINT_BGR = MASK_COVER_TINT_BGR
SILHOUETTE_ALPHA = MASK_COVER_ALPHA
EYE_REVEAL_RADIUS = 12
EYE_REVEAL_FEATHER = 6
HAND_REVEAL_FEATHER = 30

# Kunai 슬라이스 타겟 PNG 렌더 반지름 (충돌은 falling_object.DEFAULT_RADIUS 사용)
KUNAI_RENDER_SIZE = 72


# ============================================================
# 11. 폴리싱 — Hand Spotlight (프라이버시: 손만 노출)
# ============================================================
SPOTLIGHT_RADIUS_MULT = 1.6     # 손 bbox 대각선 * 이 값 = 스포트라이트 반지름
SPOTLIGHT_DARKNESS = 0.78       # 외부 영역 어두움 강도 (0~1, 클수록 어둠)
SPOTLIGHT_BLUR_PX = 51          # 경계 부드러움 (Gaussian kernel 크기, 홀수)
SPOTLIGHT_TINT_BGR = (40, 25, 55)   # 외부 영역 색상 (닌자 의상 톤)
SPOTLIGHT_MIN_RADIUS = 80       # 너무 작은 bbox에 대비한 하한
SPOTLIGHT_NO_HAND_DARKNESS = 0.85   # 손 미감지 시 전체 어둠 강도
