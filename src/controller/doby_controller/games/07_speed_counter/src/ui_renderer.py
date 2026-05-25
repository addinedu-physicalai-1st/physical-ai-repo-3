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
