#!/usr/bin/env python3
"""
SmolVLA model worker — lerobot venv에서 실행.
shared memory로 이미지/관절을 받고, Unix socket으로 GO/DONE 신호만 주고받는다.

ROS node가 자동으로 실행하므로 직접 실행할 필요 없음.
"""

import argparse
import socket
import struct
import numpy as np
import torch

from lerobot.policies.rtc.configuration_rtc import RTCConfig
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.policies import make_pre_post_processors
from lerobot.policies.utils import prepare_observation_for_inference

# 관찰/액션 레이아웃 (serving.py와 반드시 일치)
TOP_SHAPE    = (480, 640, 3)
WRIST_SHAPE  = (480, 640, 3)
STATE_DIM    = 6
CHUNK_SIZE   = 50
ACTION_DIM   = 6

TOP_BYTES    = int(np.prod(TOP_SHAPE))
WRIST_BYTES  = int(np.prod(WRIST_SHAPE))
STATE_BYTES  = STATE_DIM * 4  # float32

OBS_BYTES    = TOP_BYTES + WRIST_BYTES + STATE_BYTES
ACT_PLANES   = 2  # 0=original policy actions, 1=postprocessed robot actions
ACT_BYTES    = ACT_PLANES * CHUNK_SIZE * ACTION_DIM * 4  # float32


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-path',   required=True)
    parser.add_argument('--device',       default='cuda')
    parser.add_argument('--robot-type',   default='omx_follower')
    parser.add_argument('--socket-path',  required=True)
    parser.add_argument('--shm-obs-name', required=True)
    parser.add_argument('--shm-act-name', required=True)
    parser.add_argument('--rtc-execution-horizon', type=int, default=11)
    args = parser.parse_args()

    # ── shared memory 연결 ────────────────────────────────────────────────
    from multiprocessing.shared_memory import SharedMemory
    shm_obs = SharedMemory(name=args.shm_obs_name)
    shm_act = SharedMemory(name=args.shm_act_name)

    top_buf   = np.ndarray(TOP_SHAPE,   dtype=np.uint8,   buffer=shm_obs.buf, offset=0)
    wrist_buf = np.ndarray(WRIST_SHAPE, dtype=np.uint8,   buffer=shm_obs.buf, offset=TOP_BYTES)
    state_buf = np.ndarray(STATE_DIM,   dtype=np.float32, buffer=shm_obs.buf, offset=TOP_BYTES + WRIST_BYTES)
    act_buf   = np.ndarray((ACT_PLANES, CHUNK_SIZE, ACTION_DIM), dtype=np.float32, buffer=shm_act.buf)

    # ── 모델 로딩 (1회) ───────────────────────────────────────────────────
    print(f"[worker] Loading model from {args.model_path} on {args.device} ...", flush=True)
    model = SmolVLAPolicy.from_pretrained(args.model_path)
    model.config.rtc_config = RTCConfig(execution_horizon=args.rtc_execution_horizon)
    model.init_rtc_processor()
    model.to(args.device)
    model.eval()
    device = torch.device(args.device)

    preprocess, postprocess = make_pre_post_processors(
        model.config,
        args.model_path,
        preprocessor_overrides={"device_processor": {"device": args.device}},
    )
    print("[worker] Model loaded.", flush=True)

    # ── Unix socket 연결 ──────────────────────────────────────────────────
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(args.socket_path)

    # READY 신호
    sock.sendall(b'R')

    # ── 추론 루프 ─────────────────────────────────────────────────────────
    while True:
        cmd = sock.recv(1)
        if not cmd or cmd == b'Q':
            break

        if cmd == b'G':
            # 프로토콜: task_len(4) + task + delay(4) + has_prev(1) + [prev_len(4) + prev original bytes]
            task_len = struct.unpack('>I', _recv_exact(sock, 4))[0]
            task = _recv_exact(sock, task_len).decode('utf-8')
            inference_delay = struct.unpack('>I', _recv_exact(sock, 4))[0]
            has_prev = struct.unpack('?', _recv_exact(sock, 1))[0]
            prev_chunk_left_over = None
            if has_prev:
                prev_len = struct.unpack('>I', _recv_exact(sock, 4))[0]
                prev_bytes = _recv_exact(sock, prev_len)
                prev_arr = np.frombuffer(prev_bytes, dtype=np.float32).reshape(-1, ACTION_DIM)
                prev_chunk_left_over = torch.from_numpy(prev_arr.copy()).to(device)

            robot_type = args.robot_type

            # shared memory에서 관찰값 읽기 (copy로 안전하게)
            top   = top_buf.copy()
            wrist = wrist_buf.copy()
            state = state_buf.copy()

            obs_dict = {
                'observation.images.top':   top,
                'observation.images.wrist': wrist,
                'observation.state':        state,
            }
            obs = prepare_observation_for_inference(obs_dict, device, task, robot_type)
            # lerobot RTCInferenceEngine과 동일하게 task를 리스트로 오버라이드
            # (tokenizer는 배치 형식인 list를 기대함)
            obs['task'] = [task]
            obs = preprocess(obs)

            with torch.no_grad():
                chunk = model.predict_action_chunk(
                    obs,
                    inference_delay=inference_delay,
                    prev_chunk_left_over=prev_chunk_left_over,
                )  # (1, chunk_size, action_dim)

            original_chunk = chunk.squeeze(0).clone()
            processed_chunk = postprocess(chunk).squeeze(0)
            original_np = original_chunk.cpu().numpy()
            processed_np = processed_chunk.cpu().numpy()

            # 결과를 shared memory에 쓰기: original은 RTC prefix용, processed는 로봇 실행용
            rows = min(len(processed_np), CHUNK_SIZE)
            act_buf[:] = 0
            act_buf[0, :rows] = original_np[:rows]
            act_buf[1, :rows] = processed_np[:rows]

            sock.sendall(b'D')

    shm_obs.close()
    shm_act.close()
    sock.close()
    print("[worker] Shutdown.", flush=True)


if __name__ == '__main__':
    main()
