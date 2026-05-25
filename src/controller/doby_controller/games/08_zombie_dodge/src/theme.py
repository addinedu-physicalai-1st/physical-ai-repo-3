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
    "bomb":       (40, 40, 200),     # 빨강 (BGR이라 R=200)
}

KIND_KOREAN = {
    "americano":  "아메리카노",
    "latte":      "라떼",
    "cappuccino": "카푸치노",
    "cake":       "케이크",
    "croissant":  "크루아상",
    "bomb":       "폭탄",
}

KIND_LABEL = {
    "americano":  "AME",
    "latte":      "LAT",
    "cappuccino": "CAP",
    "cake":       "CAKE",
    "croissant":  "CROI",
    "bomb":       "X",
}


# ============================================================
# 9. W5 컬러 헌트 — 8색 팔레트 토큰
# ============================================================
HUNT_BURGUNDY = "burgundy"
HUNT_TERRACOTTA = "terracotta"
HUNT_MUSTARD = "mustard"
HUNT_SAGE = "sage"
HUNT_NAVY = "navy"
HUNT_MAUVE = "mauve"
HUNT_CREAM = "cream"
HUNT_CHARCOAL = "charcoal"
HUNT_NEUTRAL = "neutral"

# 한글 라벨 (이모지 없이)
HUNT_COLOR_KOREAN = {
    HUNT_BURGUNDY:   "버건디",
    HUNT_TERRACOTTA: "테라코타",
    HUNT_MUSTARD:    "머스타드",
    HUNT_SAGE:       "세이지",
    HUNT_NAVY:       "네이비",
    HUNT_MAUVE:      "모브",
    HUNT_CREAM:      "크림",
    HUNT_CHARCOAL:   "차콜",
    HUNT_NEUTRAL:    "기타",
}

# 짧은 영문 라벨 (객체 박스 위 텍스트용)
HUNT_COLOR_LABEL = {
    HUNT_BURGUNDY:   "BURGUNDY",
    HUNT_TERRACOTTA: "TERRA",
    HUNT_MUSTARD:    "MUSTARD",
    HUNT_SAGE:       "SAGE",
    HUNT_NAVY:       "NAVY",
    HUNT_MAUVE:      "MAUVE",
    HUNT_CREAM:      "CREAM",
    HUNT_CHARCOAL:   "CHARCOAL",
    HUNT_NEUTRAL:    "?",
}

# 8색 오버레이 BGR (run_demo PALETTE_BGR와 일관)
HUNT_COLOR_BGR = {
    HUNT_BURGUNDY:   (50, 30, 110),
    HUNT_TERRACOTTA: (60, 90, 170),
    HUNT_MUSTARD:    (60, 180, 200),
    HUNT_SAGE:       (140, 170, 160),
    HUNT_NAVY:       (90, 50, 30),
    HUNT_MAUVE:      (160, 130, 180),
    HUNT_CREAM:      (220, 235, 245),
    HUNT_CHARCOAL:   (60, 60, 60),
    HUNT_NEUTRAL:    (128, 128, 128),
}

# 게임 종료 사유별 한글
HUNT_END_REASON_KOREAN = {
    "win":     "성공!",
    "timeout": "시간 초과",
}

# 사운드 매핑
HUNT_MATCH_SOUND = "win"
HUNT_VICTORY_SOUND = "victory"
HUNT_LOSE_SOUND = "lose"


# ============================================================
# 10. W6 K-Pop 댄스 — 5종 포즈 토큰
# ============================================================
POSE_T = "t_pose"
POSE_Y = "y_pose"
POSE_LEFT_UP = "left_up"
POSE_RIGHT_UP = "right_up"
POSE_CLAP = "clap"
POSE_NEUTRAL = "neutral"

POSE_KOREAN = {
    POSE_T:        "T자",
    POSE_Y:        "Y자",
    POSE_LEFT_UP:  "왼손 위",
    POSE_RIGHT_UP: "오른손 위",
    POSE_CLAP:     "박수",
    POSE_NEUTRAL:  "무자세",
}

# 동작 안내 (Doby 시범 시 부제)
POSE_HINT = {
    POSE_T:        "양팔을 옆으로 쭉 펴세요!",
    POSE_Y:        "양손을 위로 올려 V자!",
    POSE_LEFT_UP:  "왼손은 위로, 오른팔은 옆으로",
    POSE_RIGHT_UP: "오른손은 위로, 왼팔은 옆으로",
    POSE_CLAP:     "양손을 가슴 앞에 모아 박수!",
    POSE_NEUTRAL:  "편안한 자세",
}

# Doby stick figure 색상 (BGR) — 친근한 핑크 톤
DOBY_STICK_COLOR = PINKLAB_PINK
DOBY_STICK_JOINT_COLOR = PINKLAB_PINK_LIGHT
DOBY_STICK_HEAD_COLOR = (180, 215, 240)

DANCE_VERDICT_COLOR = {
    "correct": COLOR_WIN,
    "partial": COLOR_DRAW,
    "fail":    COLOR_LOSE,
}

DANCE_VERDICT_KOREAN = {
    "correct": "정답!",
    "partial": "부분 정답",
    "fail":    "아쉬워!",
}

DANCE_VERDICT_SOUND = {
    "correct": "win",
    "partial": "win",
    "fail":    "lose",
}


# ============================================================
# 11. W7 좀비 피하기 — 토큰
# ============================================================
ZOMBIE_KIND_NORMAL = "normal"
ZOMBIE_KIND_FAST = "fast"
ZOMBIE_KIND_BIG = "big"

ZOMBIE_BODY_BGR = {
    ZOMBIE_KIND_NORMAL: (90, 130, 80),    # 좀비 그린
    ZOMBIE_KIND_FAST:   (120, 90, 180),   # 보라
    ZOMBIE_KIND_BIG:    (110, 110, 110),  # 차콜 그레이
}

ZOMBIE_EYE_COLOR = (0, 0, 60)            # 깊은 눈동자
ZOMBIE_TEETH_COLOR = COLOR_WHITE

# 회피 박스 시각화 색
DODGE_BOX_OUTLINE_COLOR = PINKLAB_PINK
DODGE_BOX_WARNING_COLOR = COLOR_DRAW     # 충돌 임박 노랑

# 효과음
ZOMBIE_HIT_SOUND = "lose"
ZOMBIE_DODGE_SOUND = "win"
ZOMBIE_VICTORY_SOUND = "victory"
ZOMBIE_GAMEOVER_SOUND = "lose"

# 좀비 종류별 한글
ZOMBIE_KIND_KOREAN = {
    ZOMBIE_KIND_NORMAL: "좀비",
    ZOMBIE_KIND_FAST:   "스피드 좀비",
    ZOMBIE_KIND_BIG:    "거대 좀비",
}
