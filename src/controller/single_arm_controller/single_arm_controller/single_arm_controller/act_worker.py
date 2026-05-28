#!/usr/bin/env python3
"""
ACT model worker — lerobot venv에서 실행.
shared memory로 이미지/관절을 받고, Unix socket으로 GO/DONE 신호만 주고받는다.

설정은 waiter.py가 전달하는 --config-path YAML 파일에서 읽는다.
모든 상수(TOP_SHAPE, CHUNK_SIZE 등)가 waiter.py와 자동으로 동기화된다.

프로토콜:
  - waiter.py가 shared memory에 top/wrist 이미지와 관절 상태를 쓴다.
  - Unix socket으로 b'G' + uint32(delay)를 보내 추론을 요청한다.
  - worker는 action chunk를 shared memory에 쓰고 b'D'로 완료를 알린다.
"""

import argparse
import socket
import struct
from pathlib import Path

import numpy as np
import torch
import yaml

from lerobot.policies.act import ACTPolicy
from lerobot.policies import make_pre_post_processors
from lerobot.policies.utils import prepare_observation_for_inference


def _load_config(path: str) -> dict:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def _recv_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        data = sock.recv(n - len(buf))
        if not data:
            raise ConnectionError('socket closed')
        buf.extend(data)
    return bytes(buf)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-path',   required=True)
    parser.add_argument('--device',       default='cuda')
    parser.add_argument('--robot-type',   default='omx_follower')
    parser.add_argument('--socket-path',  required=True)
    parser.add_argument('--shm-obs-name', required=True)
    parser.add_argument('--shm-act-name', required=True)
    parser.add_argument('--config-path',  required=True, help='waiter_config.yaml 경로')
    args = parser.parse_args()

    # ── 설정 로드 ────────────────────────────────────────────────────────────
    cfg    = _load_config(args.config_path)
    mem    = cfg['memory']

    TOP_SHAPE   = tuple(mem['top_shape'])
    WRIST_SHAPE = tuple(mem['wrist_shape'])
    STATE_DIM   = mem['state_dim']
    CHUNK_SIZE  = mem['chunk_size']
    ACTION_DIM  = mem['action_dim']

    TOP_BYTES   = int(np.prod(TOP_SHAPE))
    WRIST_BYTES = int(np.prod(WRIST_SHAPE))
    STATE_BYTES = STATE_DIM * 4
    OBS_BYTES   = TOP_BYTES + WRIST_BYTES + STATE_BYTES
    ACT_PLANES  = 2
    ACT_BYTES   = ACT_PLANES * CHUNK_SIZE * ACTION_DIM * 4

    print(
        f'[act_worker] config: chunk_size={CHUNK_SIZE} action_dim={ACTION_DIM} '
        f'state_dim={STATE_DIM} top={TOP_SHAPE} wrist={WRIST_SHAPE}',
        flush=True,
    )

    # ── shared memory 연결 ───────────────────────────────────────────────────
    from multiprocessing.shared_memory import SharedMemory
    shm_obs = SharedMemory(name=args.shm_obs_name)
    shm_act = SharedMemory(name=args.shm_act_name)

    top_buf   = np.ndarray(TOP_SHAPE,   dtype=np.uint8,   buffer=shm_obs.buf, offset=0)
    wrist_buf = np.ndarray(WRIST_SHAPE, dtype=np.uint8,   buffer=shm_obs.buf, offset=TOP_BYTES)
    state_buf = np.ndarray(STATE_DIM,   dtype=np.float32, buffer=shm_obs.buf, offset=TOP_BYTES + WRIST_BYTES)
    act_buf   = np.ndarray((ACT_PLANES, CHUNK_SIZE, ACTION_DIM), dtype=np.float32, buffer=shm_act.buf)

    # ── 모델 로딩 ────────────────────────────────────────────────────────────
    print(f'[act_worker] Loading ACT from {args.model_path} on {args.device} ...', flush=True)
    model = ACTPolicy.from_pretrained(args.model_path)
    model.to(args.device)
    model.eval()
    device = torch.device(args.device)

    model_chunk = model.config.chunk_size
    if model_chunk > CHUNK_SIZE:
        print(
            f'[act_worker] WARNING: model chunk_size={model_chunk} > CHUNK_SIZE={CHUNK_SIZE}. '
            f'memory.chunk_size를 waiter_config.yaml에서 {model_chunk} 이상으로 늘려야 한다.',
            flush=True,
        )

    preprocess, postprocess = make_pre_post_processors(
        model.config,
        args.model_path,
        preprocessor_overrides={'device_processor': {'device': args.device}},
    )
    print(f'[act_worker] Model loaded. chunk_size={model_chunk}', flush=True)

    # ── Unix socket 연결 ─────────────────────────────────────────────────────
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(args.socket_path)
    sock.sendall(b'R')   # READY

    # ── 추론 루프 ────────────────────────────────────────────────────────────
    while True:
        cmd = sock.recv(1)
        if not cmd or cmd == b'Q':
            break

        if cmd == b'G':
            # 프로토콜: uint32(inference_delay)
            inference_delay = struct.unpack('>I', _recv_exact(sock, 4))[0]

            top   = top_buf.copy()
            wrist = wrist_buf.copy()
            state = state_buf.copy()

            obs_dict = {
                'observation.images.top':   top,
                'observation.images.wrist': wrist,
                'observation.state':        state,
            }
            obs = prepare_observation_for_inference(
                obs_dict, device, task=None, robot_type=args.robot_type
            )
            obs = preprocess(obs)

            with torch.no_grad():
                chunk = model.predict_action_chunk(obs)   # (1, chunk_size, action_dim)

            original_chunk  = chunk.squeeze(0).clone()
            processed_chunk = postprocess(chunk).squeeze(0)

            rows = min(len(processed_chunk.cpu().numpy()), CHUNK_SIZE)
            act_buf[:] = 0
            act_buf[0, :rows] = original_chunk.cpu().numpy()[:rows]
            act_buf[1, :rows] = processed_chunk.cpu().numpy()[:rows]

            sock.sendall(b'D')   # DONE

    shm_obs.close()
    shm_act.close()
    sock.close()
    print('[act_worker] Shutdown.', flush=True)


if __name__ == '__main__':
    main()
