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
    from .cafe_ninja_sprite import overlay_bgra
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import theme
    from cafe_ninja_sprite import overlay_bgra


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
        
        # Anchor 적용 — 첫 글자 수평(l/m/r), 둘째 글자 수직(t/m/b).
        # 9위치 모두 지원: lt/mt/rt/lm/mm/rm/lb/mb/rb.
        if anchor[0:1] == "m":       # mt, mm, mb
            x -= text_w // 2
        elif anchor[0:1] == "r":     # rt, rm, rb
            x -= text_w
        if anchor[1:2] == "m":       # lm, mm, rm
            y -= text_h // 2
        elif anchor[1:2] == "b":     # lb, mb, rb
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


# ============================================================
# 5. W2 스피드 카운터 전용 컴포넌트
# ============================================================
def draw_speed_score_bar(frame, combo: int, win_combo: int,
                          fails: int, max_fails: int,
                          remaining_time: float):
    """W2 상단 점수바 - 콤보/오답/시간"""
    h = theme.HEADER_HEIGHT
    w = theme.SCREEN_WIDTH
    
    draw_translucent_panel(frame, (0, 0), (w, h),
                            theme.COLOR_BLACK, alpha=0.7)
    
    # 콤보 (좌측, 핑크 강조)
    combo_color = theme.PINKLAB_PINK if combo > 0 else theme.COLOR_GRAY_LIGHT
    draw_text_korean(frame, "콤보", (40, 8),
                      theme.FONT_SIZE_SMALL, combo_color, anchor="lt")
    draw_text_korean(frame, f"{combo}/{win_combo}",
                      (40, 28),
                      theme.FONT_SIZE_LARGE, combo_color, anchor="lt")
    
    # 오답 (중앙)
    fails_color = theme.COLOR_LOSE if fails >= 3 else theme.COLOR_GRAY_LIGHT
    draw_text_korean(frame, "오답", (w // 2, 8),
                      theme.FONT_SIZE_SMALL, fails_color, anchor="mt")
    draw_text_korean(frame, f"{fails}/{max_fails}",
                      (w // 2, 28),
                      theme.FONT_SIZE_LARGE, fails_color, anchor="mt")
    
    # 남은 시간 (우측)
    time_color = theme.COLOR_LOSE if remaining_time < 10 else theme.COLOR_GRAY_LIGHT
    draw_text_korean(frame, "남은 시간", (w - 30, 8),
                      theme.FONT_SIZE_SMALL, time_color, anchor="rt")
    draw_text_korean(frame, f"{remaining_time:.0f}s",
                      (w - 30, 28),
                      theme.FONT_SIZE_LARGE, time_color, anchor="rt")
    
    return frame


def draw_question_number(frame, number: int):
    """중앙에 출제 숫자 큰 표시
    
    Args:
        number: 출제 숫자 (1~10)
    """
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2 - 20
    
    # 배경 원
    cv2.circle(frame, (cx, cy), 90, (40, 40, 60), -1)
    cv2.circle(frame, (cx, cy), 90, theme.PINKLAB_PINK, 4)
    
    # 큰 숫자 (PIL)
    draw_text_korean(frame, str(number), (cx, cy),
                      120, theme.PINKLAB_PINK_LIGHT, anchor="mm")
    
    # 안내 텍스트
    draw_text_korean(frame, "이 숫자를 만드세요!", (cx, cy + 110),
                      theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE,
                      anchor="mm")
    return frame


def draw_timer_bar(frame, remaining: float, total: float):
    """타이머 바 (수평 진행 바)
    
    Args:
        remaining: 남은 시간 (초)
        total: 전체 시간 (초)
    """
    if total <= 0:
        return frame
    
    ratio = max(0.0, min(1.0, remaining / total))
    
    # 바 위치
    bar_y = theme.SCREEN_HEIGHT - 90
    bar_h = 16
    bar_left = 50
    bar_right = theme.SCREEN_WIDTH - 50
    bar_w = bar_right - bar_left
    
    # 색상 (시간에 따라 변화)
    if ratio > 0.5:
        bar_color = theme.COLOR_WIN  # 초록
    elif ratio > 0.25:
        bar_color = theme.COLOR_DRAW  # 노랑
    else:
        bar_color = theme.COLOR_LOSE  # 빨강
    
    # 배경 (어두운 회색)
    cv2.rectangle(frame, (bar_left, bar_y),
                   (bar_right, bar_y + bar_h),
                   (60, 60, 60), -1)
    
    # 채워진 부분
    filled_w = int(bar_w * ratio)
    if filled_w > 0:
        cv2.rectangle(frame, (bar_left, bar_y),
                       (bar_left + filled_w, bar_y + bar_h),
                       bar_color, -1)
    
    # 테두리
    cv2.rectangle(frame, (bar_left, bar_y),
                   (bar_right, bar_y + bar_h),
                   (200, 200, 200), 2)
    
    # 시간 텍스트 (바 위)
    time_text = f"{remaining:.1f}초 / {total:.1f}초"
    draw_text_korean(frame, time_text, (theme.SCREEN_WIDTH // 2, bar_y - 5),
                      theme.FONT_SIZE_SMALL, theme.COLOR_WHITE,
                      anchor="mb")
    
    return frame


def draw_user_count_indicator(frame, current_total, target,
                                left_count=None, right_count=None):
    """하단 사용자 손가락 표시
    
    Args:
        current_total: 현재 양손 합계 (None이면 인식 안 됨)
        target: 목표 숫자
        left_count, right_count: 각 손 개수 (None 가능)
    """
    y = theme.SCREEN_HEIGHT - 35
    cx = theme.SCREEN_WIDTH // 2
    
    if current_total is None:
        text = "양손을 보여주세요"
        color = theme.COLOR_GRAY_LIGHT
    else:
        # 좌/우 표시
        l_str = str(left_count) if left_count is not None else "-"
        r_str = str(right_count) if right_count is not None else "-"
        
        if current_total == target:
            text = f"YOU: {l_str} + {r_str} = {current_total} ✓"
            color = theme.COLOR_WIN
        else:
            text = f"YOU: {l_str} + {r_str} = {current_total}"
            color = theme.COLOR_USER
    
    draw_text_korean(frame, text, (cx, y),
                      theme.FONT_SIZE_NORMAL, color, anchor="mm")
    return frame


def draw_round_feedback(frame, is_correct: bool, target: int, user_total):
    """라운드 결과 피드백 (정답/오답 큰 표시)
    
    Args:
        is_correct: 정답 여부
        target: 목표 숫자
        user_total: 사용자가 만든 합계
    """
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    
    # 반투명 배경
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, cy - 80),
                   (theme.SCREEN_WIDTH, cy + 80),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    
    if is_correct:
        draw_text_korean(frame, "정답!", (cx, cy - 20),
                          80, theme.COLOR_WIN, anchor="mm")
        sub = f"{target} = {user_total}"
        draw_text_korean(frame, sub, (cx, cy + 40),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                          anchor="mm")
    else:
        draw_text_korean(frame, "오답", (cx, cy - 20),
                          70, theme.COLOR_LOSE, anchor="mm")
        u_str = str(user_total) if user_total is not None else "?"
        sub = f"정답: {target} (당신: {u_str})"
        draw_text_korean(frame, sub, (cx, cy + 40),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                          anchor="mm")
    
    return frame


def draw_speed_game_over(frame, win: bool, end_reason: str,
                          max_combo: int, total_correct: int,
                          total_wrong: int):
    """W2 게임 종료 화면
    
    Args:
        win: 승리 여부
        end_reason: "win" | "timeout" | "fails"
        max_combo: 최고 콤보
        total_correct: 정답 수
        total_wrong: 오답 수
    """
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    
    # 어두운 오버레이
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0),
                   (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    
    if win:
        draw_text_korean(frame, "우승!", (cx, cy - 90),
                          70, theme.COLOR_WIN, anchor="mm")
        draw_text_korean(frame, f"{max_combo}연속 정답 달성!",
                          (cx, cy - 25),
                          theme.FONT_SIZE_MEDIUM, theme.PINKLAB_PINK_LIGHT,
                          anchor="mm")
        draw_text_korean(frame, "쿠폰이 발급되었습니다",
                          (cx, cy + 15),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WIN,
                          anchor="mm")
        draw_text_korean(frame, "음료 20% 할인", (cx, cy + 50),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WIN,
                          anchor="mm")
    else:
        # 패배 사유별 메시지
        reason_msg = {
            "timeout": "시간 초과",
            "fails": "오답 5회 누적",
        }.get(end_reason, "패배")
        
        draw_text_korean(frame, reason_msg, (cx, cy - 90),
                          60, theme.COLOR_LOSE, anchor="mm")
        draw_text_korean(frame, f"최고 콤보: {max_combo}",
                          (cx, cy - 25),
                          theme.FONT_SIZE_MEDIUM, theme.COLOR_GRAY_LIGHT,
                          anchor="mm")
        draw_text_korean(frame, f"정답 {total_correct} / 오답 {total_wrong}",
                          (cx, cy + 15),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                          anchor="mm")
    
    draw_text_korean(frame, "[R] 재시작   [Q] 종료", (cx, cy + 110),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                      anchor="mm")
    
    return frame


# ============================================================
# 6. W3 카페 닌자 전용 컴포넌트
# ============================================================
def draw_finger_trail(frame, points, slicing: bool):
    """검지 끝 트레일 (그라데이션 폴리라인)"""
    if len(points) < 2:
        return frame
    base_color = theme.PINKLAB_PINK if slicing else (180, 180, 180)
    n = len(points)
    for i in range(1, n):
        alpha = i / n
        thickness = max(1, int(10 * alpha))
        color = tuple(int(c * alpha) for c in base_color)
        cv2.line(frame, points[i - 1], points[i],
                 color, thickness, cv2.LINE_AA)
    return frame


def draw_finger_tip(frame, pos, slicing: bool):
    """검지 끝 강조 점"""
    if pos is None:
        return frame
    color = theme.PINKLAB_PINK if slicing else (200, 200, 200)
    cv2.circle(frame, pos, 12, color, -1)
    cv2.circle(frame, pos, 12, theme.COLOR_WHITE, 2)
    return frame


_KUNAI_SPRITE_CACHE = {"img": None, "size": None}


def _get_kunai_sprite():
    """Kunai PNG를 처음 한 번만 로드 + theme.KUNAI_RENDER_SIZE로 리사이즈해 캐시 (BGRA)"""
    size = theme.KUNAI_RENDER_SIZE
    if _KUNAI_SPRITE_CACHE["img"] is not None and _KUNAI_SPRITE_CACHE["size"] == size:
        return _KUNAI_SPRITE_CACHE["img"]
    if not os.path.exists(theme.NINJA_KUNAI_PATH):
        return None
    img = cv2.imread(theme.NINJA_KUNAI_PATH, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    h, w = img.shape[:2]
    scale = size / max(h, w)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    _KUNAI_SPRITE_CACHE["img"] = img
    _KUNAI_SPRITE_CACHE["size"] = size
    return img


def _rotate_bgra(img, angle_deg):
    """BGRA 이미지를 angle_deg만큼 회전 (배경 투명)"""
    h, w = img.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    M = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)
    return cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def draw_falling_object(frame, obj):
    """떨어지는 메뉴 객체. kunai는 PNG 스프라이트, 나머지는 색상 원 placeholder."""
    cx, cy = obj.position()
    color = theme.KIND_COLORS.get(obj.kind, theme.COLOR_WHITE)
    is_bomb = (obj.kind == "bomb")
    is_kunai = (obj.kind == "kunai")

    if is_kunai:
        spr = _get_kunai_sprite()
        if spr is not None:
            rot = _rotate_bgra(spr, obj.angle)
            h, w = rot.shape[:2]
            overlay_bgra(frame, rot, cx - w // 2, cy - h // 2)
            return frame
        # 폴백: 회색 원
        cv2.circle(frame, (cx, cy), obj.radius, color, -1)
        cv2.circle(frame, (cx, cy), obj.radius, theme.COLOR_WHITE, 2)
        return frame

    if is_bomb:
        cv2.circle(frame, (cx, cy), obj.radius, color, -1)
        cv2.circle(frame, (cx, cy), obj.radius, (0, 0, 0), 4)
        cv2.circle(frame, (cx, cy), obj.radius - 6, (0, 0, 0), 2)
        r = obj.radius - 14
        cv2.line(frame, (cx - r, cy - r), (cx + r, cy + r),
                 theme.COLOR_WHITE, 4, cv2.LINE_AA)
        cv2.line(frame, (cx - r, cy + r), (cx + r, cy - r),
                 theme.COLOR_WHITE, 4, cv2.LINE_AA)
    else:
        cv2.circle(frame, (cx, cy), obj.radius, color, -1)
        cv2.circle(frame, (cx, cy), obj.radius, theme.COLOR_WHITE, 2)
        label = theme.KIND_LABEL.get(obj.kind, "?")
        font_scale = 0.6 if len(label) <= 3 else 0.5
        text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                     font_scale, 2)[0]
        tx = cx - text_size[0] // 2
        ty = cy + text_size[1] // 2
        cv2.putText(frame, label, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    theme.COLOR_BLACK, 3, cv2.LINE_AA)
        cv2.putText(frame, label, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    theme.COLOR_WHITE, 1, cv2.LINE_AA)
    return frame


# ============================================================
# 폴리싱 (2026-05-18): 배경 합성 + 닌자 마스코트 오버레이
# ============================================================
def draw_background(frame, bg_image):
    """배경 BGR 이미지를 theme.BACKGROUND_ALPHA 강도로 카메라 위에 블렌딩 (in-place).

    bg_image가 None이거나 사이즈 다르면 무시.
    """
    if bg_image is None:
        return frame
    if bg_image.shape[:2] != frame.shape[:2]:
        return frame
    alpha = theme.BACKGROUND_ALPHA
    cv2.addWeighted(bg_image, alpha, frame, 1.0 - alpha, 0, dst=frame)
    return frame


def draw_ninja_mascot(frame, sprite):
    """좌상단 코너에 닌자 마스코트 현재 프레임을 알파 오버레이.

    sprite가 None이면 무시.
    """
    if sprite is None:
        return frame
    img = sprite.current_frame()
    overlay_bgra(frame, img,
                 theme.MASCOT_MARGIN_X,
                 theme.MASCOT_OFFSET_Y)
    return frame


def apply_hand_spotlight(frame, hand_bbox):
    """프라이버시 스포트라이트: 손 영역만 카메라 영상 노출, 나머지 짙은 톤으로 덮음.

    Args:
        frame: BGR np.ndarray (in-place 수정)
        hand_bbox: (xmin, ymin, xmax, ymax) 또는 None (손 미감지)
    """
    h, w = frame.shape[:2]
    tint = np.array(theme.SPOTLIGHT_TINT_BGR, dtype=np.float32)

    if hand_bbox is None:
        # 손 없으면 전체 어둡게
        darkness = theme.SPOTLIGHT_NO_HAND_DARKNESS
        frame_f = frame.astype(np.float32)
        tint_layer = np.full_like(frame_f, tint)
        np.copyto(frame, (frame_f * (1.0 - darkness) + tint_layer * darkness).astype(np.uint8))
        return frame

    xmin, ymin, xmax, ymax = hand_bbox
    cx = (xmin + xmax) // 2
    cy = (ymin + ymax) // 2
    diag = int(((xmax - xmin) ** 2 + (ymax - ymin) ** 2) ** 0.5)
    radius = max(theme.SPOTLIGHT_MIN_RADIUS, int(diag * theme.SPOTLIGHT_RADIUS_MULT / 2))

    # 마스크: 외부=darkness, 원 내부=0 → 가우시안 블러로 가장자리 부드럽게
    mask = np.full((h, w), theme.SPOTLIGHT_DARKNESS, dtype=np.float32)
    cv2.circle(mask, (cx, cy), radius, 0.0, thickness=-1)

    blur_k = theme.SPOTLIGHT_BLUR_PX
    if blur_k % 2 == 0:
        blur_k += 1
    if blur_k > 1:
        mask = cv2.GaussianBlur(mask, (blur_k, blur_k), 0)

    mask_3 = mask[:, :, None]
    frame_f = frame.astype(np.float32)
    tint_layer = np.full_like(frame_f, tint)
    blended = frame_f * (1.0 - mask_3) + tint_layer * mask_3
    np.copyto(frame, blended.astype(np.uint8))
    return frame


def draw_slice_flash(frame, obj):
    """베인 객체에 한 프레임 흰 원 효과"""
    cx, cy = obj.position()
    cv2.circle(frame, (cx, cy), obj.radius + 8,
               theme.COLOR_WHITE, 3, cv2.LINE_AA)
    return frame


def draw_combo_popup(frame, multiplier: float, gained: int, pos):
    """콤보 점수 팝업"""
    if multiplier <= 1.0:
        text = f"+{gained}"
        size = theme.FONT_SIZE_NORMAL
        color = theme.COLOR_WIN
    elif multiplier < 2.0:
        text = f"COMBO! +{gained}"
        size = theme.FONT_SIZE_MEDIUM
        color = theme.PINKLAB_PINK_LIGHT
    elif multiplier < 3.0:
        text = f"GREAT COMBO! +{gained}"
        size = theme.FONT_SIZE_LARGE
        color = theme.COLOR_DRAW
    else:
        text = f"WONDER COMBO! +{gained}"
        size = theme.FONT_SIZE_HUGE
        color = theme.COLOR_LOSE
    draw_text_korean(frame, text, pos, size, color, anchor="mm")
    return frame


def draw_ninja_score_bar(frame, score: int, target: int, lives: int,
                          max_lives: int, remaining_time: float):
    """W3 상단 HUD"""
    h = theme.HEADER_HEIGHT
    w = theme.SCREEN_WIDTH

    draw_translucent_panel(frame, (0, 0), (w, h),
                            theme.COLOR_BLACK, alpha=0.7)

    progress = min(1.0, score / target) if target else 0.0
    score_color = theme.PINKLAB_PINK if progress < 1.0 else theme.COLOR_WIN

    draw_text_korean(frame, "점수", (40, 8),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="lt")
    draw_text_korean(frame, f"{score}/{target}", (40, 28),
                      theme.FONT_SIZE_LARGE, score_color, anchor="lt")

    bar_x = 180
    bar_w = 140
    bar_y = 25
    bar_h = 12
    cv2.rectangle(frame, (bar_x, bar_y),
                   (bar_x + bar_w, bar_y + bar_h),
                   (60, 60, 60), -1)
    filled = int(bar_w * progress)
    if filled > 0:
        cv2.rectangle(frame, (bar_x, bar_y),
                       (bar_x + filled, bar_y + bar_h),
                       score_color, -1)
    cv2.rectangle(frame, (bar_x, bar_y),
                   (bar_x + bar_w, bar_y + bar_h),
                   theme.COLOR_WHITE, 1)

    heart_x = w // 2
    draw_text_korean(frame, "생명", (heart_x, 8),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="mt")
    hearts = "♥" * lives + "♡" * (max_lives - lives)
    heart_color = theme.COLOR_LOSE if lives <= 1 else theme.PINKLAB_PINK
    draw_text_korean(frame, hearts, (heart_x, 28),
                      theme.FONT_SIZE_LARGE, heart_color, anchor="mt")

    time_color = theme.COLOR_LOSE if remaining_time < 10 else theme.COLOR_GRAY_LIGHT
    draw_text_korean(frame, "남은 시간", (w - 30, 8),
                      theme.FONT_SIZE_SMALL, time_color, anchor="rt")
    draw_text_korean(frame, f"{remaining_time:.0f}s",
                      (w - 30, 28),
                      theme.FONT_SIZE_LARGE, time_color, anchor="rt")
    return frame


def draw_ninja_difficulty_select(frame):
    """W3 난이도 선택"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0),
                   (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    draw_text_korean(frame, "카페 닌자", (cx, cy - 130),
                      theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "검지로 메뉴를 베어내세요!", (cx, cy - 80),
                      theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm")
    draw_text_korean(frame, "폭탄은 피하세요", (cx, cy - 50),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_LOSE, anchor="mm")
    draw_text_korean(frame, "난이도를 선택하세요", (cx, cy - 10),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE, anchor="mm")
    draw_text_korean(frame, "[1]  쉬움  (목표 200)", (cx, cy + 30),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    draw_text_korean(frame, "[2]  보통  (목표 300)", (cx, cy + 65),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")
    draw_text_korean(frame, "[3]  어려움  (목표 450)", (cx, cy + 100),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_LOSE, anchor="mm")
    draw_text_korean(frame, "[Q] 종료", (cx, cy + 160),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="mm")
    return frame


def draw_ninja_ready(frame):
    """W3 시작 대기"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    draw_text_korean(frame, "준비되셨나요?", (cx, cy - 60),
                      theme.FONT_SIZE_LARGE, theme.COLOR_WHITE, anchor="mm")
    draw_text_korean(frame, "검지를 카메라에 보여주세요", (cx, cy - 10),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                      anchor="mm")
    draw_text_korean(frame, "[SPACE] 시작", (cx, cy + 50),
                      theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "60초 안에 목표 점수 달성!", (cx, cy + 110),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")
    return frame


def draw_ninja_game_over(frame, win: bool, end_reason: str,
                          score: int, target: int,
                          max_combo: int, slices_total: int,
                          bombs_hit: int):
    """W3 게임 종료"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0),
                   (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    if win:
        draw_text_korean(frame, "우승!", (cx, cy - 110),
                          70, theme.COLOR_WIN, anchor="mm")
        draw_text_korean(frame, f"{score}점 / 목표 {target}점",
                          (cx, cy - 45),
                          theme.FONT_SIZE_MEDIUM, theme.PINKLAB_PINK_LIGHT,
                          anchor="mm")
        draw_text_korean(frame, "쿠폰이 발급되었습니다", (cx, cy - 5),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
        draw_text_korean(frame, "음료 20% 할인", (cx, cy + 30),
                          theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    else:
        reason_msg = {
            "lives_out": "생명 소진",
            "timeout": "시간 초과",
        }.get(end_reason, "패배")
        draw_text_korean(frame, reason_msg, (cx, cy - 110),
                          60, theme.COLOR_LOSE, anchor="mm")
        draw_text_korean(frame, f"{score}점 / 목표 {target}점",
                          (cx, cy - 45),
                          theme.FONT_SIZE_MEDIUM, theme.COLOR_GRAY_LIGHT,
                          anchor="mm")

    draw_text_korean(frame, f"최고 콤보: {max_combo}", (cx, cy + 60),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                      anchor="mm")
    draw_text_korean(frame,
                      f"메뉴 베기 {slices_total}회   폭탄 {bombs_hit}회",
                      (cx, cy + 90),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="mm")
    draw_text_korean(frame, "[R] 재시작   [Q] 종료", (cx, cy + 140),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE, anchor="mm")
    return frame


def draw_speed_difficulty_select(frame):
    """W2 난이도 선택 화면"""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0),
                   (theme.SCREEN_WIDTH, theme.SCREEN_HEIGHT),
                   theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    draw_text_korean(frame, "스피드 카운터", (cx, cy - 130),
                      theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK, anchor="mm")

    draw_text_korean(frame, "5연속 정답에 도전!", (cx, cy - 80),
                      theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm")

    draw_text_korean(frame, "난이도를 선택하세요", (cx, cy - 30),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE, anchor="mm")

    draw_text_korean(frame, "[1]  쉬움  (4초/문제)", (cx, cy + 20),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    draw_text_korean(frame, "[2]  보통  (3초/문제)", (cx, cy + 55),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")
    draw_text_korean(frame, "[3]  어려움  (2초/문제)", (cx, cy + 90),
                      theme.FONT_SIZE_NORMAL, theme.COLOR_LOSE, anchor="mm")

    draw_text_korean(frame, "[Q] 종료", (cx, cy + 150),
                      theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                      anchor="mm")

    return frame


# ============================================================
# 7. 실루엣 마스크 헬퍼 함수
# ============================================================
def _build_disk_mask(shape, center, radius, feather):
    """원형 마스크 (float32 0~1). 중심=1, 외곽=Gaussian 감쇠.

    Args:
        shape: (H, W). center: (x, y) 픽셀 좌표. radius: 단단한 영역 반지름.
        feather: 경계 부드러움 (sigma 픽셀). 0이면 hard edge.
    """
    h, w = shape
    cx, cy = center
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32)
    if feather <= 0:
        return (dist <= radius).astype(np.float32)
    inside = dist <= radius
    outside_falloff = np.exp(-((dist - radius) ** 2) / (2 * feather * feather))
    mask = np.where(inside, 1.0, outside_falloff).astype(np.float32)
    return mask


def _build_circular_mask(shape, bbox, feather, min_radius=80):
    """손 bbox 기준 원형 마스크.

    bbox: (x1, y1, x2, y2) — 21개 landmark의 axis-aligned bbox (finger_tracker.get_hand_bbox 형식).
    중심 = bbox 중심, 반지름 = max(min_radius, 대각선 * 0.8).
    """
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    diag = float(np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2))
    radius = max(min_radius, int(diag * 0.8))
    return _build_disk_mask(shape, (cx, cy), radius, feather)


def _build_inverted_triangle_mask(shape, top_left, top_right, bottom, feather, border_thickness=0):
    """역삼각형 ▽ 마스크 (float32 0~1).

    꼭짓점 3개: top_left, top_right (위 변 좌/우), bottom (아래 꼭짓점).
    border_thickness > 0이면 외곽에 anti-aliased 굵은 선 추가 (마스크 면적 살짝 확장 + 솔기 느낌).
    feather > 0이면 Gaussian blur로 경계 부드럽게 (마스크 답게는 0 권장).
    """
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)
    pts = np.array([top_left, top_right, bottom], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255, lineType=cv2.LINE_AA)
    if border_thickness > 0:
        cv2.polylines(mask, [pts], isClosed=True, color=255,
                       thickness=int(border_thickness), lineType=cv2.LINE_AA)
    if feather > 0:
        k = max(3, int(feather * 2) | 1)
        mask = cv2.GaussianBlur(mask, (k, k), float(feather))
    return mask.astype(np.float32) / 255.0


def apply_silhouette(frame, person_mask, eye_points, hand_bbox, bg_image,
                      nose_point=None, mouth_point=None):
    """닌자 복면 합성 (in-place).

    흐름:
    - 배경 영역 (person_mask 외) → town.jpg 원색
    - 사람 영역 → 카메라 그대로 노출 (얼굴/몸 다 보임)
    - 코+입 영역 → 자주톤 ellipse 마스크 (전통 닌자 마스크)

    `eye_points` / `hand_bbox`은 레거시 호환 (현 흐름에서는 사용 X).
    """
    if bg_image is None or bg_image.shape != frame.shape:
        return frame

    camera_pixels = frame.copy()

    # 1) 사람 미검출 → 배경만
    if person_mask is None:
        frame[:] = bg_image
        return frame

    if person_mask.shape != frame.shape[:2]:
        person_mask = cv2.resize(person_mask, (frame.shape[1], frame.shape[0]),
                                  interpolation=cv2.INTER_NEAREST)

    mask_f = (person_mask.astype(np.float32) / 255.0)[..., None]
    mask_2d = mask_f[..., 0]

    # 2) 사람 = 카메라, 배경 = bg_image
    blended = camera_pixels.astype(np.float32) * mask_f + bg_image.astype(np.float32) * (1.0 - mask_f)

    # 3) 코 위 ~ 턱 아래 역삼각형 ▽ 검정 마스크 (닌자 복면)
    if mouth_point is not None:
        nx, ny = nose_point if nose_point is not None else mouth_point
        mx, my = mouth_point
        nm_dist = max(abs(my - ny), 8)

        # 양 눈 거리 (위 변 폭 기준). 없으면 nose-mouth 거리의 3배로 폴백.
        if len(eye_points) == 2:
            ex0, _ = eye_points[0]
            ex1, _ = eye_points[1]
            eye_dist = max(abs(ex1 - ex0), 24)
        else:
            eye_dist = nm_dist * 3

        half_w = int(eye_dist * theme.MASK_COVER_TOP_WIDTH_RATIO)
        top_y = int(ny + nm_dist * theme.MASK_COVER_TOP_Y_OFFSET_RATIO)
        bottom_y = int(my + nm_dist * theme.MASK_COVER_BOTTOM_Y_OFFSET_RATIO)

        top_left = (nx - half_w, top_y)
        top_right = (nx + half_w, top_y)
        bottom = (mx, bottom_y)

        cover = _build_inverted_triangle_mask(frame.shape[:2], top_left, top_right, bottom,
                                                feather=theme.MASK_COVER_FEATHER,
                                                border_thickness=theme.MASK_COVER_BORDER_THICKNESS)
        cover = cover * mask_2d  # 배경 영역엔 안 그림
        cm = (cover * theme.MASK_COVER_ALPHA)[..., None]

        tint = np.full_like(camera_pixels, theme.MASK_COVER_TINT_BGR, dtype=np.uint8).astype(np.float32)
        blended = tint * cm + blended * (1.0 - cm)

    frame[:] = np.clip(blended, 0, 255).astype(np.uint8)
    return frame
