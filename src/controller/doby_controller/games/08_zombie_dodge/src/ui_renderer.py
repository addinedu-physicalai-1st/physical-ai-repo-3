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


def draw_falling_object(frame, obj):
    """떨어지는 메뉴 객체 (placeholder: 색상 원 + 영문 라벨)"""
    cx, cy = obj.position()
    color = theme.KIND_COLORS.get(obj.kind, theme.COLOR_WHITE)
    is_bomb = (obj.kind == "bomb")

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
# 9. W5 컬러 헌트 — 친근한 도형 헬퍼
# ============================================================
def _draw_rounded_rect_fill(frame, p1, p2, color, radius=14):
    """채워진 둥근 사각형 (직접 그리기)."""
    x1, y1 = p1
    x2, y2 = p2
    if x2 - x1 < radius * 2 or y2 - y1 < radius * 2:
        cv2.rectangle(frame, p1, p2, color, -1)
        return
    cv2.rectangle(frame, (x1 + radius, y1), (x2 - radius, y2), color, -1)
    cv2.rectangle(frame, (x1, y1 + radius), (x2, y2 - radius), color, -1)
    cv2.circle(frame, (x1 + radius, y1 + radius), radius, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (x2 - radius, y1 + radius), radius, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (x1 + radius, y2 - radius), radius, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (x2 - radius, y2 - radius), radius, color, -1, cv2.LINE_AA)


def _draw_rounded_rect_outline(frame, p1, p2, color, thickness=2, radius=14):
    """둥근 사각형 외곽선."""
    x1, y1 = p1
    x2, y2 = p2
    if x2 - x1 < radius * 2 or y2 - y1 < radius * 2:
        cv2.rectangle(frame, p1, p2, color, thickness, cv2.LINE_AA)
        return
    # 변 4개
    cv2.line(frame, (x1 + radius, y1), (x2 - radius, y1),
             color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x1 + radius, y2), (x2 - radius, y2),
             color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x1, y1 + radius), (x1, y2 - radius),
             color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x2, y1 + radius), (x2, y2 - radius),
             color, thickness, cv2.LINE_AA)
    # 호 4개
    cv2.ellipse(frame, (x1 + radius, y1 + radius), (radius, radius),
                180, 0, 90, color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x2 - radius, y1 + radius), (radius, radius),
                270, 0, 90, color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x1 + radius, y2 - radius), (radius, radius),
                90, 0, 90, color, thickness, cv2.LINE_AA)
    cv2.ellipse(frame, (x2 - radius, y2 - radius), (radius, radius),
                0, 0, 90, color, thickness, cv2.LINE_AA)


def draw_rounded_panel(frame, p1, p2, color=theme.COLOR_PANEL_BG,
                       alpha=0.7, radius=18, outline_color=None,
                       outline_thickness=1):
    """반투명 둥근 패널 (그라데이션 카드 느낌)."""
    overlay = frame.copy()
    _draw_rounded_rect_fill(overlay, p1, p2, color, radius=radius)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    if outline_color is not None:
        _draw_rounded_rect_outline(frame, p1, p2, outline_color,
                                    outline_thickness, radius=radius)


def draw_soft_shadow(frame, p1, p2, radius=18, offset=4, alpha=0.35):
    """카드 뒤에 깔리는 부드러운 그림자 (둥근 사각형 어두운 패널)."""
    x1, y1 = p1
    x2, y2 = p2
    sp1 = (x1 + offset, y1 + offset)
    sp2 = (x2 + offset, y2 + offset)
    overlay = frame.copy()
    _draw_rounded_rect_fill(overlay, sp1, sp2, (0, 0, 0), radius=radius)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def draw_color_dot(frame, center, radius, bgr_color,
                   outline_color=None, outline_thickness=3,
                   highlight=True):
    """친근한 색 원 — 광택 하이라이트 포함.

    Args:
        center: (cx, cy)
        radius: 원 반지름
        bgr_color: 채움 색
        outline_color: 외곽선 색. None이면 외곽 없음.
        highlight: True면 좌상단에 부드러운 흰 광택 추가 → 친근한 느낌
    """
    cx, cy = center
    cv2.circle(frame, (cx, cy), radius, bgr_color, -1, cv2.LINE_AA)
    if outline_color is not None:
        cv2.circle(frame, (cx, cy), radius, outline_color,
                   outline_thickness, cv2.LINE_AA)
    if highlight and radius >= 12:
        # 좌상단 광택 (작은 흰 원, 살짝 떨어진 위치)
        hl_radius = max(3, radius // 4)
        hl_offset = max(2, radius // 3)
        hl_center = (cx - hl_offset, cy - hl_offset)
        # 부드러운 광택을 위해 두 단계 원
        overlay = frame.copy()
        cv2.circle(overlay, hl_center, hl_radius + 3,
                   theme.COLOR_WHITE, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)
        cv2.circle(frame, hl_center, hl_radius,
                   theme.COLOR_WHITE, -1, cv2.LINE_AA)


def draw_progress_dots(frame, center_x, y, collected, goal,
                       dot_radius=14, spacing=10):
    """진행도 시각화 — 채워진 둥근 점 + 빈 둥근 점.

    수집 N개 → 처음 N개 점은 윈 색(체크) + 광택, 나머지는 회색 외곽선만.
    """
    if goal <= 0:
        return
    total_w = goal * (dot_radius * 2) + (goal - 1) * spacing
    start_x = center_x - total_w // 2 + dot_radius
    for i in range(goal):
        cx = start_x + i * (dot_radius * 2 + spacing)
        if i < collected:
            draw_color_dot(frame, (cx, y), dot_radius,
                           theme.COLOR_WIN,
                           outline_color=theme.COLOR_WHITE,
                           outline_thickness=2,
                           highlight=True)
        else:
            # 빈 점 — 어두운 채움 + 밝은 외곽
            cv2.circle(frame, (cx, y), dot_radius,
                       (60, 60, 70), -1, cv2.LINE_AA)
            cv2.circle(frame, (cx, y), dot_radius,
                       theme.COLOR_GRAY_LIGHT, 2, cv2.LINE_AA)


def draw_rounded_object_box(frame, bbox, color, thickness=2,
                            radius=10, outline_color=None,
                            outline_thickness=0):
    """객체 박스 — 둥근 모서리."""
    x1, y1, x2, y2 = bbox
    if outline_color is not None and outline_thickness > 0:
        _draw_rounded_rect_outline(
            frame, (x1 - 3, y1 - 3), (x2 + 3, y2 + 3),
            outline_color, outline_thickness, radius=radius + 3,
        )
    _draw_rounded_rect_outline(
        frame, (x1, y1), (x2, y2), color, thickness, radius=radius
    )


# ============================================================
# 9b. W5 컬러 헌트 전용 컴포넌트
# ============================================================
def _draw_difficulty_badge(frame, center, label_kr, key_label, accent_bgr,
                           radius=28):
    """난이도 옆 색 점 배지 — '[1] 쉬움' 라인의 좌측에 배치."""
    draw_color_dot(frame, center, radius, accent_bgr,
                   outline_color=theme.COLOR_WHITE,
                   outline_thickness=2, highlight=True)
    draw_text_korean(frame, key_label, center,
                     theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE,
                     anchor="mm", shadow=True)


def draw_hunt_difficulty_select(frame):
    """W5 난이도 선택 — 둥근 카드 + 색 배지."""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    # 전체 어두운 배경 (꽉 채움)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    # 중앙 카드 패널
    panel_w = 460
    panel_h = 360
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    draw_soft_shadow(frame, p1, p2, radius=22, offset=5, alpha=0.45)
    draw_rounded_panel(frame, p1, p2,
                       color=(38, 32, 56),  # 따뜻한 다크 패널
                       alpha=0.92, radius=22,
                       outline_color=theme.PINKLAB_PINK,
                       outline_thickness=2)

    # 타이틀
    draw_text_korean(frame, "컬러 헌트", (cx, cy - 130),
                     theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "매장 속 미션 색 물건을 찾아주세요",
                     (cx, cy - 85),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm", shadow=False)

    # 가는 구분선
    cv2.line(frame, (cx - 160, cy - 55), (cx + 160, cy - 55),
             theme.PINKLAB_PINK_DARK, 1, cv2.LINE_AA)

    # 난이도 3개 라인 (좌측에 색 점 배지 + 우측 한글 안내)
    diffs = [
        ("1", "쉬움  ·  90초  ·  2개  찾기", theme.COLOR_WIN),
        ("2", "보통  ·  60초  ·  3개  찾기", theme.PINKLAB_PINK),
        ("3", "어려움  ·  45초  ·  4개  찾기", theme.COLOR_LOSE),
    ]
    badge_x = cx - 160
    text_x = cx - 100
    base_y = cy - 5
    for i, (key, label, color) in enumerate(diffs):
        y = base_y + i * 50
        _draw_difficulty_badge(frame, (badge_x, y), label, key, color,
                               radius=24)
        draw_text_korean(frame, label, (text_x, y),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                         anchor="lm")

    draw_text_korean(frame, "[Q]  종료", (cx, cy + 150),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                     anchor="mm", shadow=False)
    return frame


def draw_hunt_ready(frame, mission):
    """READY: 큰 둥근 색 원 + 미션 카드 + SPACE 안내."""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    color_kr = theme.HUNT_COLOR_KOREAN.get(mission.target_color, "??")
    swatch_bgr = theme.HUNT_COLOR_BGR.get(mission.target_color,
                                          theme.COLOR_GRAY_LIGHT)

    # 미션 카드 패널
    panel_w = 420
    panel_h = 380
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    draw_soft_shadow(frame, p1, p2, radius=24, offset=6, alpha=0.45)
    draw_rounded_panel(frame, p1, p2,
                       color=(40, 34, 60), alpha=0.94, radius=24,
                       outline_color=swatch_bgr, outline_thickness=3)

    # 상단 작은 라벨
    draw_text_korean(frame, "미션", (cx, cy - 140),
                     theme.FONT_SIZE_NORMAL, theme.PINKLAB_PINK_LIGHT,
                     anchor="mm", shadow=False)

    # 큰 둥근 색 원 (광택 포함 — 친근함의 핵심)
    draw_color_dot(frame, (cx, cy - 60), 60, swatch_bgr,
                   outline_color=theme.COLOR_WHITE,
                   outline_thickness=4, highlight=True)

    # 색 이름
    draw_text_korean(frame, f"{color_kr} 색", (cx, cy + 30),
                     theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK_LIGHT,
                     anchor="mm")

    # 진행 점 미리보기 (모두 빈 상태)
    draw_progress_dots(frame, cx, cy + 80, 0, mission.goal_count,
                       dot_radius=11, spacing=8)

    # 안내
    goal_str = (f"{mission.goal_count}개  ·  제한시간 "
                f"{int(mission.time_limit)}초")
    draw_text_korean(frame, goal_str, (cx, cy + 113),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm", shadow=False)

    draw_text_korean(frame, "[SPACE]  시작", (cx, cy + 155),
                     theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK, anchor="mm")

    # 하단 친근한 안내 (카드 밖)
    draw_text_korean(frame, "매장을 천천히 둘러보세요 ✨".replace("✨", ""),
                     (cx, cy + 215),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm", shadow=False)
    return frame


def draw_hunt_score_bar(frame, mission, collected, remaining):
    """W5 상단 HUD: 둥근 카드 3개 (찾을 색 / 진행 점 / 남은 시간)."""
    h = 76  # 더 큰 HUD
    w = theme.SCREEN_WIDTH

    # 둥근 배경 패널 (좌우 약간 inset)
    inset = 8
    p1 = (inset, 6)
    p2 = (w - inset, h - 2)
    draw_soft_shadow(frame, p1, p2, radius=18, offset=3, alpha=0.35)
    draw_rounded_panel(frame, p1, p2,
                       color=(30, 26, 46), alpha=0.85, radius=18,
                       outline_color=theme.PINKLAB_PINK_DARK,
                       outline_thickness=1)

    swatch_bgr = theme.HUNT_COLOR_BGR.get(mission.target_color,
                                          theme.COLOR_GRAY_LIGHT)
    color_kr = theme.HUNT_COLOR_KOREAN.get(mission.target_color, "??")

    # ---- 좌측: 미션 색 원 + 한글 ----
    draw_color_dot(frame, (44, 39), 19, swatch_bgr,
                   outline_color=theme.COLOR_WHITE,
                   outline_thickness=2, highlight=True)
    draw_text_korean(frame, "찾을 색", (74, 14),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                     anchor="lt", shadow=False)
    draw_text_korean(frame, color_kr, (74, 32),
                     theme.FONT_SIZE_MEDIUM, theme.PINKLAB_PINK_LIGHT,
                     anchor="lt")

    # ---- 중앙: 진행 점 ----
    draw_progress_dots(frame, w // 2, 40, collected, mission.goal_count,
                       dot_radius=12, spacing=6)

    # ---- 우측: 남은 시간 ----
    time_color = theme.COLOR_LOSE if remaining < 10 else theme.COLOR_GRAY_LIGHT
    draw_text_korean(frame, "남은 시간", (w - 30, 14),
                     theme.FONT_SIZE_SMALL, time_color,
                     anchor="rt", shadow=False)
    big_time = (theme.PINKLAB_PINK_LIGHT if remaining < 10
                else theme.COLOR_WHITE)
    draw_text_korean(frame, f"{remaining:.0f}s", (w - 30, 32),
                     theme.FONT_SIZE_LARGE, big_time, anchor="rt")
    return frame


def draw_hunt_object_boxes(frame, matches, target_color,
                           confidence_gate: float):
    """프레임 객체별 둥근 박스 + 라벨 칩.

    - 매칭 + 게이트 통과 = 굵은 색 박스 + 흰 외곽 + 색 점 뱃지
    - 그 외 = 가는 색 박스
    """
    for m in matches:
        x1, y1, x2, y2 = m.bbox
        color = theme.HUNT_COLOR_BGR.get(m.detected_color,
                                          (128, 128, 128))
        is_strong_match = (
            m.is_target_match
            and m.color_confidence >= confidence_gate
        )
        if is_strong_match:
            draw_rounded_object_box(
                frame, m.bbox, color, thickness=4, radius=12,
                outline_color=theme.COLOR_WHITE, outline_thickness=2,
            )
            # 좌상단에 친근한 색 점 (체크 느낌)
            draw_color_dot(frame, (x1 + 2, y1 + 2), 9, color,
                           outline_color=theme.COLOR_WHITE,
                           outline_thickness=2, highlight=False)
        else:
            draw_rounded_object_box(
                frame, m.bbox, color, thickness=2, radius=10,
                outline_color=None, outline_thickness=0,
            )

        label = (
            f"{m.yolo_class} · "
            f"{theme.HUNT_COLOR_LABEL.get(m.detected_color, '?')} "
            f"{m.color_confidence:.2f}"
        )
        cv2.putText(frame, label, (x1 + 16, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, theme.COLOR_BLACK,
                    3, cv2.LINE_AA)
        cv2.putText(frame, label, (x1 + 16, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return frame


def draw_hunt_match_flash(frame, bbox):
    """매칭 +1 시 한 프레임 흰 둥근 외곽선 강조."""
    x1, y1, x2, y2 = bbox
    _draw_rounded_rect_outline(
        frame, (x1 - 7, y1 - 7), (x2 + 7, y2 + 7),
        theme.COLOR_WHITE, 4, radius=14,
    )
    return frame


def _draw_medal(frame, center, outer_color, inner_color, radius=58):
    """우승 메달 — 큰 둥근 원 + 내부 별 형태(다각형)."""
    cx, cy = center
    # 외곽
    cv2.circle(frame, (cx, cy), radius + 6, outer_color, -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), radius, theme.COLOR_WHITE, -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), radius, outer_color, 4, cv2.LINE_AA)
    # 내부 색 채움
    cv2.circle(frame, (cx, cy), radius - 14, inner_color, -1, cv2.LINE_AA)
    # 광택
    overlay = frame.copy()
    hl_radius = radius // 3
    cv2.circle(overlay, (cx - radius // 3, cy - radius // 3),
               hl_radius, theme.COLOR_WHITE, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)


def draw_hunt_game_over(frame, win: bool, summary: dict):
    """W5 게임 종료 — 둥근 카드 + 우승 시 메달."""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    # 어두운 배경
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    color_kr = theme.HUNT_COLOR_KOREAN.get(summary["target_color"], "??")
    swatch_bgr = theme.HUNT_COLOR_BGR.get(summary["target_color"],
                                           theme.COLOR_GRAY_LIGHT)

    # 결과 카드
    panel_w = 460
    panel_h = 400
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    accent = theme.PINKLAB_PINK if win else (90, 90, 130)
    draw_soft_shadow(frame, p1, p2, radius=24, offset=6, alpha=0.5)
    draw_rounded_panel(frame, p1, p2,
                       color=(38, 32, 56), alpha=0.95, radius=24,
                       outline_color=accent, outline_thickness=2)

    # 메달 또는 빈 도형
    if win:
        _draw_medal(frame, (cx, cy - 110),
                    outer_color=theme.PINKLAB_PINK,
                    inner_color=theme.COLOR_WIN,
                    radius=52)
        draw_text_korean(frame, "성공!", (cx, cy - 30),
                         70, theme.COLOR_WIN, anchor="mm")
    else:
        # 작은 색 점 + 슬픈 표정 안내
        draw_color_dot(frame, (cx, cy - 110), 50, swatch_bgr,
                       outline_color=theme.COLOR_WHITE,
                       outline_thickness=3, highlight=True)
        # 도전 실패 메시지 한글
        msg = theme.HUNT_END_REASON_KOREAN.get(
            summary["end_reason"], "도전 실패"
        )
        draw_text_korean(frame, msg, (cx, cy - 30),
                         60, theme.COLOR_LOSE, anchor="mm")

    # 색·수집 요약
    draw_text_korean(
        frame,
        f"{color_kr}  ·  {summary['collected']}/{summary['goal_count']}개",
        (cx, cy + 30),
        theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm",
    )

    # 진행 점 미니뷰
    draw_progress_dots(frame, cx, cy + 70, summary["collected"],
                       summary["goal_count"],
                       dot_radius=10, spacing=7)

    if win:
        draw_text_korean(frame, "쿠폰이 발급되었습니다", (cx, cy + 110),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WIN,
                         anchor="mm", shadow=False)
        draw_text_korean(frame, "음료 20% 할인", (cx, cy + 138),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    else:
        draw_text_korean(frame, "다시 도전해보세요!", (cx, cy + 110),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                         anchor="mm", shadow=False)

    stat = (
        f"시도 {summary['attempts']}   "
        f"색 X {summary['rejected_by_color']}   "
        f"신뢰 X {summary['rejected_by_confidence']}   "
        f"중복 {summary['rejected_by_dedup']}"
    )
    draw_text_korean(frame, stat, (cx, cy + 168),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                     anchor="mm", shadow=False)

    # 하단 안내 (카드 밖)
    draw_text_korean(frame, "[R]  재시작     [Q]  종료",
                     (cx, sh - 30),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                     anchor="mm")
    return frame


# ============================================================
# 10. W6 K-Pop 댄스 — Doby stick figure + 화면들
# ============================================================
def _stick_segment(frame, p1, p2, color, thickness=4):
    """관절 한 segment (선 + 양 끝 작은 원)."""
    cv2.line(frame, p1, p2, color, thickness, cv2.LINE_AA)
    cv2.circle(frame, p1, max(2, thickness // 2 + 1),
               theme.DOBY_STICK_JOINT_COLOR, -1, cv2.LINE_AA)
    cv2.circle(frame, p2, max(2, thickness // 2 + 1),
               theme.DOBY_STICK_JOINT_COLOR, -1, cv2.LINE_AA)


def draw_doby_stick_figure(frame, pose, center, scale=140):
    """Doby의 stick figure — 5종 포즈를 작은 도형으로 시각화.

    Args:
        pose: theme.POSE_T / POSE_Y / POSE_LEFT_UP / POSE_RIGHT_UP / POSE_CLAP
        center: (cx, cy) — 머리 중심 픽셀 좌표
        scale: 전체 신체 높이 픽셀 (머리부터 다리 끝까지 ~)
    """
    cx, cy = center
    head_r = max(8, int(scale * 0.10))

    # 머리 (둥근 원 + 광택)
    draw_color_dot(frame, (cx, cy), head_r, theme.DOBY_STICK_HEAD_COLOR,
                   outline_color=theme.DOBY_STICK_COLOR,
                   outline_thickness=3, highlight=True)

    # 어깨 중심 / 골반 중심
    shoulder_y = cy + head_r + int(scale * 0.04)
    hip_y = shoulder_y + int(scale * 0.30)
    foot_y = hip_y + int(scale * 0.30)
    sh_dx = int(scale * 0.20)
    sh_left = (cx - sh_dx, shoulder_y)
    sh_right = (cx + sh_dx, shoulder_y)
    hip_left = (cx - int(sh_dx * 0.7), hip_y)
    hip_right = (cx + int(sh_dx * 0.7), hip_y)

    # 척추
    cv2.line(frame, (cx, shoulder_y), (cx, hip_y),
             theme.DOBY_STICK_COLOR, 4, cv2.LINE_AA)
    # 어깨 line
    cv2.line(frame, sh_left, sh_right,
             theme.DOBY_STICK_COLOR, 4, cv2.LINE_AA)
    # 다리 (항상 똑같이 약간 벌림)
    foot_left = (cx - int(sh_dx * 0.6), foot_y)
    foot_right = (cx + int(sh_dx * 0.6), foot_y)
    _stick_segment(frame, hip_left, foot_left, theme.DOBY_STICK_COLOR, 4)
    _stick_segment(frame, hip_right, foot_right, theme.DOBY_STICK_COLOR, 4)

    # 팔 위치는 포즈마다 다름
    arm_seg = int(scale * 0.22)

    def horizontal_arm(shoulder, side):
        """T자 — 어깨에서 옆으로 수평. side=-1(왼쪽)/+1(오른쪽)."""
        elbow = (shoulder[0] + side * arm_seg, shoulder[1])
        wrist = (elbow[0] + side * arm_seg, elbow[1])
        return elbow, wrist

    def up_arm(shoulder, side):
        """Y자 — 위로 V자 (대각선 위)."""
        elbow = (shoulder[0] + side * int(arm_seg * 0.4),
                 shoulder[1] - int(arm_seg * 0.85))
        wrist = (elbow[0] + side * int(arm_seg * 0.3),
                 elbow[1] - int(arm_seg * 0.85))
        return elbow, wrist

    def straight_up_arm(shoulder, side):
        """왼/오른손 위 — 거의 수직."""
        elbow = (shoulder[0] + side * int(arm_seg * 0.1),
                 shoulder[1] - int(arm_seg * 0.85))
        wrist = (elbow[0] + side * int(arm_seg * 0.05),
                 elbow[1] - int(arm_seg * 0.85))
        return elbow, wrist

    def clap_arm(shoulder, side):
        """박수 — 양손이 가슴 앞에서 만남."""
        elbow_x = shoulder[0] + side * int(arm_seg * 0.4)
        elbow_y = shoulder[1] + int(arm_seg * 0.2)
        wrist_x = cx + side * 3  # 거의 중앙
        wrist_y = shoulder[1] + int(arm_seg * 0.35)
        return (elbow_x, elbow_y), (wrist_x, wrist_y)

    if pose == theme.POSE_T:
        l_e, l_w = horizontal_arm(sh_left, -1)
        r_e, r_w = horizontal_arm(sh_right, +1)
    elif pose == theme.POSE_Y:
        l_e, l_w = up_arm(sh_left, -1)
        r_e, r_w = up_arm(sh_right, +1)
    elif pose == theme.POSE_LEFT_UP:
        l_e, l_w = straight_up_arm(sh_left, -1)
        r_e, r_w = horizontal_arm(sh_right, +1)
    elif pose == theme.POSE_RIGHT_UP:
        l_e, l_w = horizontal_arm(sh_left, -1)
        r_e, r_w = straight_up_arm(sh_right, +1)
    elif pose == theme.POSE_CLAP:
        l_e, l_w = clap_arm(sh_left, -1)
        r_e, r_w = clap_arm(sh_right, +1)
    else:  # neutral
        # 차렷 자세
        l_e = (sh_left[0], sh_left[1] + arm_seg)
        l_w = (l_e[0], l_e[1] + arm_seg)
        r_e = (sh_right[0], sh_right[1] + arm_seg)
        r_w = (r_e[0], r_e[1] + arm_seg)

    _stick_segment(frame, sh_left, l_e, theme.DOBY_STICK_COLOR, 4)
    _stick_segment(frame, l_e, l_w, theme.DOBY_STICK_COLOR, 4)
    _stick_segment(frame, sh_right, r_e, theme.DOBY_STICK_COLOR, 4)
    _stick_segment(frame, r_e, r_w, theme.DOBY_STICK_COLOR, 4)
    return frame


def draw_dance_difficulty_select(frame):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    panel_w = 460
    panel_h = 380
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    draw_soft_shadow(frame, p1, p2, radius=22, offset=5, alpha=0.45)
    draw_rounded_panel(frame, p1, p2,
                       color=(38, 32, 56), alpha=0.92, radius=22,
                       outline_color=theme.PINKLAB_PINK,
                       outline_thickness=2)

    draw_text_korean(frame, "K-Pop 댄스", (cx, cy - 145),
                     theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "Doby의 안무를 따라 추세요!", (cx, cy - 100),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm", shadow=False)
    draw_text_korean(frame, "5라운드 · 4정답 이상 승리", (cx, cy - 70),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")

    cv2.line(frame, (cx - 160, cy - 40), (cx + 160, cy - 40),
             theme.PINKLAB_PINK_DARK, 1, cv2.LINE_AA)

    diffs = [
        ("1", "쉬움  ·  3.5초  ·  60%", theme.COLOR_WIN),
        ("2", "보통  ·  2.5초  ·  70%", theme.PINKLAB_PINK),
        ("3", "어려움  ·  1.5초  ·  80%", theme.COLOR_LOSE),
    ]
    badge_x = cx - 160
    text_x = cx - 100
    base_y = cy + 10
    for i, (key, label, color) in enumerate(diffs):
        y = base_y + i * 50
        draw_color_dot(frame, (badge_x, y), 24, color,
                       outline_color=theme.COLOR_WHITE,
                       outline_thickness=2, highlight=True)
        draw_text_korean(frame, key, (badge_x, y),
                         theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE,
                         anchor="mm")
        draw_text_korean(frame, label, (text_x, y),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                         anchor="lm")

    draw_text_korean(frame, "[Q]  종료", (cx, cy + 165),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                     anchor="mm", shadow=False)
    return frame


def draw_dance_ready(frame):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    draw_text_korean(frame, "준비되셨나요?", (cx, cy - 60),
                     theme.FONT_SIZE_LARGE, theme.COLOR_WHITE, anchor="mm")
    draw_text_korean(frame, "온몸이 화면에 보이도록 서주세요",
                     (cx, cy - 15),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm")
    draw_text_korean(frame, "[SPACE]  시작", (cx, cy + 40),
                     theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "Doby의 안무를 따라하세요!", (cx, cy + 100),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")
    return frame


def draw_dance_score_bar(frame, round_index, total_rounds,
                         score, max_score, correct_count):
    """W6 상단 HUD — 라운드 / 점수 / 진행 점."""
    h = 70
    w = theme.SCREEN_WIDTH

    p1 = (8, 6)
    p2 = (w - 8, h - 2)
    draw_soft_shadow(frame, p1, p2, radius=18, offset=3, alpha=0.35)
    draw_rounded_panel(frame, p1, p2,
                       color=(30, 26, 46), alpha=0.85, radius=18,
                       outline_color=theme.PINKLAB_PINK_DARK,
                       outline_thickness=1)

    # 좌측: 라운드
    draw_text_korean(frame, "라운드", (32, 12),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                     anchor="lt", shadow=False)
    draw_text_korean(frame, f"{round_index}/{total_rounds}", (32, 30),
                     theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK,
                     anchor="lt")

    # 중앙: 진행 점 (정답 수)
    draw_progress_dots(frame, w // 2, 36, correct_count,
                       total_rounds, dot_radius=11, spacing=6)

    # 우측: 점수
    progress = (score / max_score) if max_score else 0.0
    score_color = (theme.PINKLAB_PINK_LIGHT if progress >= 0.8
                   else theme.COLOR_WHITE)
    draw_text_korean(frame, "점수", (w - 30, 12),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                     anchor="rt", shadow=False)
    draw_text_korean(frame, f"{score}", (w - 30, 30),
                     theme.FONT_SIZE_LARGE, score_color, anchor="rt")
    return frame


def draw_dance_show_doby(frame, target_pose):
    """SHOW_DOBY 페이즈 — 큰 stick figure + 한글 라벨."""
    cx = theme.SCREEN_WIDTH // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    overlay = frame.copy()
    cv2.rectangle(overlay,
                  (0, 76),
                  (sw, sh),
                  theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    # 큰 stick figure (화면 중앙 위쪽)
    draw_doby_stick_figure(frame, target_pose,
                           center=(cx, sh // 2 - 80),
                           scale=240)

    label = theme.POSE_KOREAN.get(target_pose, "??")
    hint = theme.POSE_HINT.get(target_pose, "")
    draw_text_korean(frame, f"Doby: {label}!", (cx, sh - 90),
                     theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, hint, (cx, sh - 50),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE, anchor="mm")
    return frame


def draw_dance_countdown(frame, count: int, target_pose=None):
    """카운트다운 + 우상단 미니 stick figure."""
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    overlay = frame.copy()
    cv2.circle(overlay, (cx, cy), 80, theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
    draw_text_korean(frame, str(count), (cx, cy),
                     95, theme.PINKLAB_PINK, anchor="mm")

    if target_pose is not None:
        draw_doby_stick_figure(frame, target_pose,
                               center=(theme.SCREEN_WIDTH - 75,
                                       110),
                               scale=110)
        label = theme.POSE_KOREAN.get(target_pose, "??")
        draw_text_korean(frame, label,
                         (theme.SCREEN_WIDTH - 75, 195),
                         theme.FONT_SIZE_SMALL, theme.PINKLAB_PINK,
                         anchor="mm")
    return frame


def draw_dance_measure(frame, target_pose, accuracy: float,
                       remaining: float, total: float,
                       correct_threshold: float,
                       partial_threshold: float):
    """측정 중 — 정확도 게이지 + 미니 Doby + 남은 시간."""
    draw_doby_stick_figure(frame, target_pose,
                           center=(theme.SCREEN_WIDTH - 75, 110),
                           scale=110)
    label = theme.POSE_KOREAN.get(target_pose, "??")
    draw_text_korean(frame, label,
                     (theme.SCREEN_WIDTH - 75, 195),
                     theme.FONT_SIZE_SMALL, theme.PINKLAB_PINK,
                     anchor="mm")

    draw_text_korean(frame, f"{label} 자세를 따라하세요!",
                     (theme.SCREEN_WIDTH // 2, 100),
                     theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE,
                     anchor="mm")

    # 정확도 게이지 (W4 face accuracy gauge와 동일 위치)
    accuracy = max(0.0, min(1.0, accuracy))
    bar_y = theme.SCREEN_HEIGHT - 90
    bar_h = 18
    bar_left = 50
    bar_right = theme.SCREEN_WIDTH - 50
    bar_w = bar_right - bar_left

    cv2.rectangle(frame, (bar_left, bar_y),
                  (bar_right, bar_y + bar_h),
                  (60, 60, 60), -1)
    fill_w = int(bar_w * accuracy)
    if accuracy >= 0.70:
        color = theme.COLOR_WIN
    elif accuracy >= 0.40:
        color = theme.COLOR_DRAW
    else:
        color = theme.COLOR_LOSE
    if fill_w > 0:
        cv2.rectangle(frame, (bar_left, bar_y),
                      (bar_left + fill_w, bar_y + bar_h),
                      color, -1)
    partial_x = bar_left + int(bar_w * partial_threshold)
    correct_x = bar_left + int(bar_w * correct_threshold)
    cv2.line(frame, (partial_x, bar_y - 4),
             (partial_x, bar_y + bar_h + 4),
             theme.COLOR_GRAY_LIGHT, 2, cv2.LINE_AA)
    cv2.line(frame, (correct_x, bar_y - 4),
             (correct_x, bar_y + bar_h + 4),
             theme.COLOR_WHITE, 2, cv2.LINE_AA)
    cv2.rectangle(frame, (bar_left, bar_y),
                  (bar_right, bar_y + bar_h),
                  theme.COLOR_WHITE, 1)

    pct = f"정확도: {int(accuracy * 100)}%"
    draw_text_korean(frame, pct,
                     (theme.SCREEN_WIDTH // 2, bar_y - 8),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                     anchor="mb")

    time_y = theme.SCREEN_HEIGHT - 55
    time_color = (theme.COLOR_LOSE if remaining < 0.5
                  else theme.COLOR_WHITE)
    draw_text_korean(frame,
                     f"남은 시간: {remaining:.1f}s / {total:.1f}s",
                     (theme.SCREEN_WIDTH // 2, time_y),
                     theme.FONT_SIZE_NORMAL, time_color, anchor="mm")
    return frame


def draw_dance_round_result(frame, outcome):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, cy - 95),
                  (theme.SCREEN_WIDTH, cy + 95),
                  theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    verdict = outcome["verdict"]
    msg = theme.DANCE_VERDICT_KOREAN.get(verdict, "???")
    color = theme.DANCE_VERDICT_COLOR.get(verdict, theme.COLOR_WHITE)

    draw_text_korean(frame, msg, (cx, cy - 40),
                     theme.FONT_SIZE_HUGE, color, anchor="mm")

    pose_kr = theme.POSE_KOREAN.get(outcome["target"], "??")
    sub = f"{pose_kr}  |  정확도 {int(outcome['accuracy'] * 100)}%"
    draw_text_korean(frame, sub, (cx, cy + 20),
                     theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm")
    gained = f"+{outcome['score']}점"
    gained_color = (theme.COLOR_WIN if outcome['score'] > 0
                    else theme.COLOR_GRAY_LIGHT)
    draw_text_korean(frame, gained, (cx, cy + 60),
                     theme.FONT_SIZE_NORMAL, gained_color, anchor="mm")
    return frame


def draw_dance_pose_landmarks(frame, landmarks, frame_w, frame_h):
    """Pose 33 landmark 중 핵심 관절 점 표시 (디버그 효과)."""
    key_indices = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
    color = (180, 130, 230)
    for i in key_indices:
        if 0 <= i < len(landmarks):
            lm = landmarks[i]
            x = int(lm.x * frame_w)
            y = int(lm.y * frame_h)
            cv2.circle(frame, (x, y), 3, color, -1, cv2.LINE_AA)
    return frame


def draw_dance_game_over(frame, win: bool, summary: dict):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    panel_w = 460
    panel_h = 400
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    accent = theme.PINKLAB_PINK if win else (90, 90, 130)
    draw_soft_shadow(frame, p1, p2, radius=24, offset=6, alpha=0.5)
    draw_rounded_panel(frame, p1, p2,
                       color=(38, 32, 56), alpha=0.95, radius=24,
                       outline_color=accent, outline_thickness=2)

    if win:
        _draw_medal(frame, (cx, cy - 110),
                    outer_color=theme.PINKLAB_PINK,
                    inner_color=theme.COLOR_WIN,
                    radius=52)
        draw_text_korean(frame, "우승!", (cx, cy - 30),
                         70, theme.COLOR_WIN, anchor="mm")
    else:
        # 작은 stick figure (neutral) + LOSE 메시지
        draw_doby_stick_figure(frame, theme.POSE_NEUTRAL,
                               (cx, cy - 110), scale=130)
        draw_text_korean(frame, "도전 부족", (cx, cy - 30),
                         60, theme.COLOR_LOSE, anchor="mm")

    draw_text_korean(
        frame,
        f"{summary['score']}/{summary['max_score']}점",
        (cx, cy + 25),
        theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm",
    )
    draw_progress_dots(frame, cx, cy + 70,
                       summary["correct"], summary["total_rounds"],
                       dot_radius=11, spacing=7)

    if win:
        draw_text_korean(frame, "쿠폰이 발급되었습니다", (cx, cy + 115),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WIN,
                         anchor="mm", shadow=False)
        draw_text_korean(frame, "음료 20% 할인", (cx, cy + 145),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    else:
        draw_text_korean(frame, "다시 도전해보세요!", (cx, cy + 115),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                         anchor="mm", shadow=False)

    stat = (
        f"정답 {summary['correct']}  ·  "
        f"부분 {summary['partial']}  ·  "
        f"실패 {summary['fail']}"
    )
    draw_text_korean(frame, stat, (cx, cy + 175),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                     anchor="mm", shadow=False)

    draw_text_korean(frame, "[R]  재시작     [Q]  종료",
                     (cx, sh - 30),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                     anchor="mm")
    return frame


# ============================================================
# 11. W7 좀비 피하기 — 좀비 도형 + 회피 박스 + 화면
# ============================================================
def draw_zombie(frame, zombie):
    """친근하면서 살짝 무서운 좀비 — 둥근 원 + 광택 + 눈·이빨."""
    cx, cy = int(zombie.x), int(zombie.y)
    r = zombie.radius
    body_color = theme.ZOMBIE_BODY_BGR.get(
        zombie.kind,
        theme.ZOMBIE_BODY_BGR[theme.ZOMBIE_KIND_NORMAL],
    )

    # 본체 — 둥근 원 + 흰 광택
    draw_color_dot(frame, (cx, cy), r, body_color,
                   outline_color=theme.COLOR_BLACK,
                   outline_thickness=2, highlight=True)

    # 눈 2개 (흰 흰자 + 빨강 동공)
    eye_dx = int(r * 0.30)
    eye_dy = int(r * 0.10)
    eye_r = max(3, int(r * 0.16))
    eye_l = (cx - eye_dx, cy - eye_dy)
    eye_r_pos = (cx + eye_dx, cy - eye_dy)
    cv2.circle(frame, eye_l, eye_r + 1, theme.COLOR_WHITE, -1, cv2.LINE_AA)
    cv2.circle(frame, eye_r_pos, eye_r + 1, theme.COLOR_WHITE,
               -1, cv2.LINE_AA)
    cv2.circle(frame, eye_l, eye_r, theme.ZOMBIE_EYE_COLOR,
               -1, cv2.LINE_AA)
    cv2.circle(frame, eye_r_pos, eye_r, theme.ZOMBIE_EYE_COLOR,
               -1, cv2.LINE_AA)

    # 입 + 이빨
    mouth_y = cy + int(r * 0.35)
    mouth_left_x = cx - int(r * 0.35)
    mouth_right_x = cx + int(r * 0.35)
    cv2.line(frame, (mouth_left_x, mouth_y),
             (mouth_right_x, mouth_y),
             theme.COLOR_BLACK, 2, cv2.LINE_AA)
    tooth_w = max(1, (mouth_right_x - mouth_left_x) // 3)
    for i in range(1, 4):
        tx = mouth_left_x + tooth_w * (i - 1) + tooth_w // 2
        cv2.line(frame, (tx, mouth_y - 3),
                 (tx, mouth_y + 4),
                 theme.ZOMBIE_TEETH_COLOR, 2, cv2.LINE_AA)
    return frame


def draw_person_outline(frame, person, warning: bool = False, thickness: int = 3):
    """사람 마스크 외곽선을 frame 위에 그림.

    Args:
        frame: BGR ndarray (in-place)
        person: PersonMask 또는 None
        warning: True면 경고 색상 (hit 직후)
    """
    if person is None:
        return frame
    color = (theme.DODGE_BOX_WARNING_COLOR if warning
             else theme.DODGE_BOX_OUTLINE_COLOR)
    contours, _ = cv2.findContours(
        person.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if contours:
        cv2.drawContours(frame, contours, -1, color, thickness, cv2.LINE_AA)
    return frame


def draw_dodge_score_bar(frame, score, target, lives, max_lives, remaining):
    """W7 상단 HUD — 점수 / 생명 / 시간."""
    h = 76
    w = theme.SCREEN_WIDTH

    p1 = (8, 6)
    p2 = (w - 8, h - 2)
    draw_soft_shadow(frame, p1, p2, radius=18, offset=3, alpha=0.35)
    draw_rounded_panel(frame, p1, p2,
                       color=(30, 26, 46), alpha=0.85, radius=18,
                       outline_color=theme.PINKLAB_PINK_DARK,
                       outline_thickness=1)

    # 좌측 점수
    progress = (score / target) if target else 0.0
    score_color = (theme.COLOR_WIN if progress >= 1.0
                   else theme.PINKLAB_PINK)
    draw_text_korean(frame, "점수", (32, 14),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                     anchor="lt", shadow=False)
    draw_text_korean(frame, f"{score}/{target}", (32, 32),
                     theme.FONT_SIZE_LARGE, score_color, anchor="lt")

    # 점수 진행 바
    bar_x = 200
    bar_w_total = 100
    bar_y = 30
    bar_h = 12
    cv2.rectangle(frame, (bar_x, bar_y),
                  (bar_x + bar_w_total, bar_y + bar_h),
                  (60, 60, 60), -1)
    filled = int(bar_w_total * min(1.0, progress))
    if filled > 0:
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + filled, bar_y + bar_h),
                      score_color, -1)
    cv2.rectangle(frame, (bar_x, bar_y),
                  (bar_x + bar_w_total, bar_y + bar_h),
                  theme.COLOR_WHITE, 1)

    # 중앙 생명 (둥근 점)
    heart_x = w // 2 - 30
    heart_y = 36
    heart_r = 9
    spacing = 24
    for i in range(max_lives):
        cx_h = heart_x + i * spacing
        if i < lives:
            draw_color_dot(frame, (cx_h, heart_y), heart_r,
                           theme.PINKLAB_PINK,
                           outline_color=theme.COLOR_WHITE,
                           outline_thickness=2, highlight=True)
        else:
            cv2.circle(frame, (cx_h, heart_y), heart_r,
                       (60, 60, 70), -1, cv2.LINE_AA)
            cv2.circle(frame, (cx_h, heart_y), heart_r,
                       theme.COLOR_GRAY_LIGHT, 2, cv2.LINE_AA)
    draw_text_korean(frame, "생명", (heart_x - 12, 12),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_LIGHT,
                     anchor="lt", shadow=False)

    # 우측 남은 시간
    time_color = (theme.COLOR_LOSE if remaining < 10
                  else theme.COLOR_GRAY_LIGHT)
    draw_text_korean(frame, "남은 시간", (w - 30, 14),
                     theme.FONT_SIZE_SMALL, time_color,
                     anchor="rt", shadow=False)
    big_time = (theme.PINKLAB_PINK_LIGHT if remaining < 10
                else theme.COLOR_WHITE)
    draw_text_korean(frame, f"{remaining:.0f}s", (w - 30, 32),
                     theme.FONT_SIZE_LARGE, big_time, anchor="rt")
    return frame


def draw_dodge_difficulty_select(frame):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    panel_w = 460
    panel_h = 380
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    draw_soft_shadow(frame, p1, p2, radius=22, offset=5, alpha=0.45)
    draw_rounded_panel(frame, p1, p2,
                       color=(38, 32, 56), alpha=0.92, radius=22,
                       outline_color=theme.PINKLAB_PINK,
                       outline_thickness=2)

    draw_text_korean(frame, "좀비 피하기", (cx, cy - 145),
                     theme.FONT_SIZE_HUGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "위에서 떨어지는 좀비를 몸으로 피해요!",
                     (cx, cy - 100),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm", shadow=False)
    draw_text_korean(frame, "60초 · 생명 3 · 목표 점수 달성",
                     (cx, cy - 70),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")

    cv2.line(frame, (cx - 160, cy - 40), (cx + 160, cy - 40),
             theme.PINKLAB_PINK_DARK, 1, cv2.LINE_AA)

    diffs = [
        ("1", "쉬움  ·  목표 100점", theme.COLOR_WIN),
        ("2", "보통  ·  목표 200점", theme.PINKLAB_PINK),
        ("3", "어려움  ·  목표 350점", theme.COLOR_LOSE),
    ]
    badge_x = cx - 160
    text_x = cx - 100
    base_y = cy + 10
    for i, (key, label, color) in enumerate(diffs):
        y = base_y + i * 50
        draw_color_dot(frame, (badge_x, y), 24, color,
                       outline_color=theme.COLOR_WHITE,
                       outline_thickness=2, highlight=True)
        draw_text_korean(frame, key, (badge_x, y),
                         theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE,
                         anchor="mm")
        draw_text_korean(frame, label, (text_x, y),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                         anchor="lm")

    draw_text_korean(frame, "[Q]  종료", (cx, cy + 165),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                     anchor="mm", shadow=False)
    return frame


def draw_dodge_ready(frame):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2

    draw_text_korean(frame, "준비되셨나요?", (cx, cy - 60),
                     theme.FONT_SIZE_LARGE, theme.COLOR_WHITE, anchor="mm")
    draw_text_korean(frame, "상체가 화면에 보이도록 서주세요",
                     (cx, cy - 15),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                     anchor="mm")
    draw_text_korean(frame, "[SPACE]  시작", (cx, cy + 40),
                     theme.FONT_SIZE_LARGE, theme.PINKLAB_PINK, anchor="mm")
    draw_text_korean(frame, "좌우로 몸을 움직여 좀비를 피해요!",
                     (cx, cy + 100),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_DRAW, anchor="mm")
    return frame


def draw_dodge_game_over(frame, win: bool, summary: dict):
    cx = theme.SCREEN_WIDTH // 2
    cy = theme.SCREEN_HEIGHT // 2
    sw = theme.SCREEN_WIDTH
    sh = theme.SCREEN_HEIGHT

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (sw, sh), theme.COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    panel_w = 460
    panel_h = 400
    p1 = (cx - panel_w // 2, cy - panel_h // 2)
    p2 = (cx + panel_w // 2, cy + panel_h // 2)
    accent = theme.PINKLAB_PINK if win else (90, 90, 130)
    draw_soft_shadow(frame, p1, p2, radius=24, offset=6, alpha=0.5)
    draw_rounded_panel(frame, p1, p2,
                       color=(38, 32, 56), alpha=0.95, radius=24,
                       outline_color=accent, outline_thickness=2)

    if win:
        _draw_medal(frame, (cx, cy - 110),
                    outer_color=theme.PINKLAB_PINK,
                    inner_color=theme.COLOR_WIN,
                    radius=52)
        draw_text_korean(frame, "생존!", (cx, cy - 30),
                         70, theme.COLOR_WIN, anchor="mm")
    else:
        from collections import namedtuple
        Z = namedtuple("Z", ["x", "y", "radius", "kind"])
        fake_z = Z(x=cx, y=cy - 110, radius=44,
                   kind=theme.ZOMBIE_KIND_NORMAL)
        draw_zombie(frame, fake_z)
        reason_kor = {
            "lives_out": "생명 소진",
            "timeout":   "시간 초과",
        }.get(summary.get("end_reason"), "패배")
        draw_text_korean(frame, reason_kor, (cx, cy - 30),
                         60, theme.COLOR_LOSE, anchor="mm")

    draw_text_korean(
        frame,
        f"{summary['score']}/{summary['target']}점",
        (cx, cy + 25),
        theme.FONT_SIZE_MEDIUM, theme.COLOR_WHITE, anchor="mm",
    )
    draw_progress_dots(frame, cx, cy + 70,
                       summary["lives"], summary["max_lives"],
                       dot_radius=11, spacing=7)

    if win:
        draw_text_korean(frame, "쿠폰이 발급되었습니다", (cx, cy + 115),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WIN,
                         anchor="mm", shadow=False)
        draw_text_korean(frame, "음료 20% 할인", (cx, cy + 145),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_WIN, anchor="mm")
    else:
        draw_text_korean(frame, "다시 도전해보세요!", (cx, cy + 115),
                         theme.FONT_SIZE_NORMAL, theme.COLOR_GRAY_LIGHT,
                         anchor="mm", shadow=False)

    stat = (
        f"회피 {summary['dodged_total']}  ·  "
        f"충돌 {summary['hit_total']}"
    )
    draw_text_korean(frame, stat, (cx, cy + 175),
                     theme.FONT_SIZE_SMALL, theme.COLOR_GRAY_MID,
                     anchor="mm", shadow=False)

    draw_text_korean(frame, "[R]  재시작     [Q]  종료",
                     (cx, sh - 30),
                     theme.FONT_SIZE_NORMAL, theme.COLOR_WHITE,
                     anchor="mm")
    return frame
