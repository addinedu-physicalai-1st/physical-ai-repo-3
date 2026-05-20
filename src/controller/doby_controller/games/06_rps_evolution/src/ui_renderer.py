"""
ui_renderer.py - 한글 UI 렌더러 (배치 최적화 버전)
====================================================

[성능 최적화]
- 매 텍스트마다 BGR↔RGB 변환하면 매우 느림 (8fps)
- 한 프레임의 모든 텍스트를 모았다가 한 번에 그림 (30fps+)

사용법:
    1. 프레임 시작 시: begin_frame()
    2. 그리고 싶은 만큼: draw_text_korean(...) 호출 (큐에 쌓임)
    3. 프레임 끝에: flush_text(frame)  ← 실제 렌더링

Author: Stephen (gjkong)
Date: 2026-04-30 (Step 5 최적화)
"""

import os
import sys
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 직접 실행 / 모듈 실행 둘 다 지원
try:
    from . import theme
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import theme


# ============================================================
# 1. 한글 폰트 자동 탐색
# ============================================================
KOREAN_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/gulim.ttc",
    "./assets/fonts/NanumGothic.ttf",
]


def find_korean_font():
    for font_path in KOREAN_FONT_CANDIDATES:
        if os.path.exists(font_path):
            return font_path
    return None


KOREAN_FONT_PATH = find_korean_font()

if KOREAN_FONT_PATH is None:
    print("⚠️  한글 폰트를 찾을 수 없습니다.")
    print("   Linux: sudo apt install fonts-nanum")
else:
    print(f"✅ 한글 폰트 로드: {KOREAN_FONT_PATH}")


# ============================================================
# 2. 폰트 캐시
# ============================================================
_font_cache = {}


def get_font(size: int):
    if size in _font_cache:
        return _font_cache[size]
    
    if KOREAN_FONT_PATH:
        try:
            font = ImageFont.truetype(KOREAN_FONT_PATH, size)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    
    _font_cache[size] = font
    return font


def bgr_to_rgb(color):
    return (color[2], color[1], color[0])


# ============================================================
# 3. 텍스트 큐 (배치 렌더링용)
# ============================================================
_text_queue = []  # [(text, x, y, size, color_rgb, anchor, shadow), ...]


def begin_frame():
    """프레임 시작 시 큐 초기화"""
    global _text_queue
    _text_queue = []


def draw_text_korean(frame, text, position, font_size, color,
                      anchor="lt", shadow=True):
    """텍스트를 큐에 추가 (실제 그리기는 flush_text에서)
    
    Args:
        frame: (호환성 위해 유지, 실제 사용 X)
        text: 표시할 텍스트
        position: (x, y) 좌표
        font_size: 폰트 크기
        color: BGR 튜플
        anchor: "lt", "mt", "mm", "lb", "rb"
        shadow: 그림자 효과
    
    Returns:
        frame (변경 없이 반환, 호환성 위해)
    """
    global _text_queue
    _text_queue.append({
        "text": text,
        "position": position,
        "font_size": font_size,
        "color_rgb": bgr_to_rgb(color),
        "anchor": anchor,
        "shadow": shadow,
    })
    return frame


def flush_text(frame):
    """큐에 쌓인 모든 텍스트를 한 번에 렌더링
    
    BGR↔RGB 변환을 단 1회만 수행 (성능 최적화 핵심).
    """
    global _text_queue
    
    if not _text_queue:
        return frame
    
    # BGR → RGB 변환 (1회만)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(pil_image)
    shadow_color = (0, 0, 0)
    
    # 큐의 모든 텍스트를 한 번의 PIL 세션에서 처리
    for item in _text_queue:
        text = item["text"]
        x, y = item["position"]
        font = get_font(item["font_size"])
        color_rgb = item["color_rgb"]
        anchor = item["anchor"]
        shadow = item["shadow"]
        
        # 텍스트 크기 계산 (anchor 처리)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except Exception:
            text_w = item["font_size"] * len(text) // 2
            text_h = item["font_size"]
        
        # Anchor 적용
        if anchor in ("mt", "mm"):
            x -= text_w // 2
        if anchor == "rb":
            x -= text_w
        if anchor == "mm":
            y -= text_h // 2
        if anchor in ("lb", "rb"):
            y -= text_h
        
        # 그림자
        if shadow:
            draw.text((x + 2, y + 2), text, font=font, fill=shadow_color)
        # 본 텍스트
        draw.text((x, y), text, font=font, fill=color_rgb)
    
    # PIL → BGR (1회만)
    frame_bgr = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    np.copyto(frame, frame_bgr)
    
    # 큐 비우기
    _text_queue = []
    return frame


# ============================================================
# 4. UI 컴포넌트 (텍스트 외 도형은 OpenCV로 직접 그림)
# ============================================================
def draw_translucent_panel(frame, top_left, bottom_right,
                            color=theme.COLOR_PANEL_BG, alpha=0.6):
    """반투명 패널 (OpenCV 직접 - 빠름)"""
    overlay = frame.copy()
    cv2.rectangle(overlay, top_left, bottom_right, color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    return frame


def draw_score_bar(frame, user_score, ai_score, max_score,
                    difficulty, round_number):
    """상단 점수 바"""
    h = theme.HEADER_HEIGHT
    w = theme.SCREEN_WIDTH
    
    # 배경 (도형 - OpenCV)
    draw_translucent_panel(frame, (0, 0), (w, h),
                            theme.COLOR_BLACK, alpha=0.7)
    
    # 텍스트 (큐에 추가)
    cy = h // 2
    
    draw_text_korean(frame, "USER", (40, 15),
                      theme.FONT_SIZE_SMALL, theme.COLOR_USER, anchor="lt")
    draw_text_korean(frame, str(user_score), (40, 35),
                      theme.FONT_SIZE_LARGE, theme.COLOR_USER, anchor="lt")
    
    draw_text_korean(frame, "VS", (w // 2, cy),
                      theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE,
                      anchor="mm")
    
    draw_text_korean(frame, "Doby", (w // 2 + 100, 15),
                      theme.FONT_SIZE_SMALL, theme.COLOR_AI, anchor="lt")
    draw_text_korean(frame, str(ai_score), (w // 2 + 100, 35),
                      theme.FONT_SIZE_LARGE, theme.COLOR_AI, anchor="lt")
    
    diff_text = f"난이도: {theme.DIFFICULTY_KOREAN.get(difficulty, difficulty)}"
    diff_color = theme.DIFFICULTY_COLOR.get(difficulty, theme.COLOR_WHITE)
    draw_text_korean(frame, diff_text, (w - 30, 20),
                      theme.FONT_SIZE_NORMAL, diff_color, anchor="rb")
    
    round_text = f"R{round_number} (3선 2승)"
    draw_text_korean(frame, round_text, (w - 30, 75),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="rb")
    
    return frame


def draw_ai_area(frame, ai_shape=None, is_revealed=False):
    """AI 영역"""
    y_start = theme.AI_AREA_Y
    y_end = y_start + theme.AI_AREA_HEIGHT
    cx = theme.SCREEN_WIDTH // 2
    cy = (y_start + y_end) // 2
    
    draw_translucent_panel(frame, (0, y_start),
                            (theme.SCREEN_WIDTH, y_end),
                            theme.COLOR_AI, alpha=0.15)
    
    draw_text_korean(frame, "Doby", (cx, y_start + 30),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_AI, anchor="mm")
    
    if ai_shape and is_revealed:
        text = theme.SHAPE_KOREAN.get(ai_shape, "??")
        draw_text_korean(frame, text, (cx, cy + 20),
                          theme.FONT_SIZE_HUGE, theme.COLOR_AI, anchor="mm")
    else:
        draw_text_korean(frame, "?", (cx, cy + 20),
                          theme.FONT_SIZE_HUGE, theme.COLOR_GRAY_MID,
                          anchor="mm")
    
    return frame


def draw_message_bar(frame, message, color=None):
    """중앙 메시지 바"""
    y_start = theme.MESSAGE_AREA_Y
    y_end = y_start + theme.MESSAGE_AREA_HEIGHT
    cx = theme.SCREEN_WIDTH // 2
    cy = (y_start + y_end) // 2
    
    if color is None:
        color = theme.COLOR_WHITE
    
    draw_translucent_panel(frame, (0, y_start),
                            (theme.SCREEN_WIDTH, y_end),
                            theme.COLOR_BLACK, alpha=0.5)
    
    draw_text_korean(frame, message, (cx, cy),
                      theme.FONT_SIZE_MEDIUM, color, anchor="mm")
    return frame


def draw_user_indicator(frame, current_shape, hand_detected):
    """하단 사용자 인식 상태"""
    y = theme.SCREEN_HEIGHT - 40
    cx = theme.SCREEN_WIDTH // 2
    
    if not hand_detected:
        text = "손을 보여주세요"
        color = theme.COLOR_GRAY_LIGHT
    elif current_shape == "unknown":
        text = "손 모양 인식 중..."
        color = theme.COLOR_DRAW
    else:
        text = f"YOU: {theme.SHAPE_KOREAN.get(current_shape, '??')}"
        color = theme.COLOR_USER
    
    draw_text_korean(frame, text, (cx, y),
                      theme.FONT_SIZE_NORMAL, color, anchor="mm")
    return frame


def draw_countdown(frame, count: int):
    """카운트다운 큰 숫자"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    
    overlay = frame.copy()
    cv2.circle(overlay, (cx, cy), 80, theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
    
    draw_text_korean(frame, str(count), (cx, cy),
                      90, theme.PINKLAB_PINK, anchor="mm")
    return frame


def draw_round_result(frame, result, user_shape, ai_shape):
    """라운드 결과"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    
    result_data = {
        "user_win": ("승리!", theme.COLOR_WIN),
        "ai_win": ("패배", theme.COLOR_LOSE),
        "draw": ("무승부", theme.COLOR_DRAW),
    }
    msg, color = result_data.get(result, ("???", theme.COLOR_WHITE))
    
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, cy - 70),
                   (theme.SCREEN_WIDTH, cy + 70),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    
    draw_text_korean(frame, msg, (cx, cy - 20),
                      theme.FONT_SIZE_HUGE, color, anchor="mm")
    
    user_text = theme.SHAPE_KOREAN.get(user_shape, "??")
    ai_text = theme.SHAPE_KOREAN.get(ai_shape, "??")
    compare_text = f"YOU: {user_text}   vs   Doby: {ai_text}"
    draw_text_korean(frame, compare_text, (cx, cy + 40),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                      anchor="mm")
    
    return frame


def draw_game_over(frame, winner: str):
    """게임 종료 화면"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0),
                   (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    
    if winner == "user":
        draw_text_korean(frame, "우승!", (cx, cy - 60),
                          70, theme.COLOR_WIN, anchor="mm")
        draw_text_korean(frame, "쿠폰이 발급되었습니다!", (cx, cy + 10),
                          theme.FONT_SIZE_MEDIUM, theme.PINKLAB_PINK_LIGHT,
                          anchor="mm")
        draw_text_korean(frame, "음료 20% 할인", (cx, cy + 50),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WIN,
                          anchor="mm")
    else:
        draw_text_korean(frame, "패배", (cx, cy - 60),
                          70, theme.COLOR_LOSE, anchor="mm")
        draw_text_korean(frame, "다시 도전해 보세요!", (cx, cy + 10),
                          theme.FONT_SIZE_MEDIUM, theme.COLOR_GRAY_LIGHT,
                          anchor="mm")
    
    draw_text_korean(frame, "[R] 재시작   [Q] 종료", (cx, cy + 100),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                      anchor="mm")
    
    return frame


def draw_difficulty_select(frame):
    """난이도 선택 화면"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0),
                   (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    
    draw_text_korean(frame, "Doby를 이겨라~", (cx, cy - 130),
                      theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK, anchor="mm")
    
    draw_text_korean(frame, "난이도를 선택하세요", (cx, cy - 70),
                      theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm")
    
    draw_text_korean(frame, "[1]  쉬움  (어린이도 OK)", (cx, cy - 10),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    draw_text_korean(frame, "[2]  보통  (추천)", (cx, cy + 30),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")
    draw_text_korean(frame, "[3]  어려움  (고수)", (cx, cy + 70),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_LOSE, anchor="mm")
    
    draw_text_korean(frame, "[Q] 종료", (cx, cy + 130),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="mm")
    
    return frame


def draw_fps(frame, fps: float):
    """좌하단 FPS"""
    text = f"FPS: {fps:.0f}"
    draw_text_korean(frame, text, (10, theme.SCREEN_HEIGHT - 10),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                      anchor="lb", shadow=False)
    return frame
