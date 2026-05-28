#!/usr/bin/env python3
"""
ACT model worker — lerobot venv에서 실행.
shared memory로 이미지/관절을 받고, Unix socket으로 GO/DONE 신호만 주고받는다.

설정은 act_serving_orchestrator.py가 전달하는 --config-path YAML 파일에서 읽는다.
이미지 shape, action chunk 크기 등은 act_serving_config.yaml로 동기화된다.

프로토콜:
  - act_serving_orchestrator.py가 shared memory에 top/wrist 이미지와 관절 상태를 쓴다.
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


def load_act_serving_config(path: str) -> dict:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def receive_exactly(sock, n: int) -> bytes:
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
    parser.add_argument('--config-path',  required=True, help='act_serving_config.yaml 경로')
    args = parser.parse_args()

    # ── 설정 로드 ────────────────────────────────────────────────────────────
    config = load_act_serving_config(args.config_path)
    memory_config = config['memory']

    top_image_shape = tuple(memory_config['top_shape'])
    wrist_image_shape = tuple(memory_config['wrist_shape'])
    state_dimension = memory_config['state_dim']
    action_chunk_size = memory_config['chunk_size']
    action_dimension = memory_config['action_dim']

    top_image_bytes = int(np.prod(top_image_shape))
    wrist_image_bytes = int(np.prod(wrist_image_shape))
    action_planes = 2

    print(
        f'[act_policy_worker] config: chunk_size={action_chunk_size} '
        f'action_dim={action_dimension} state_dim={state_dimension} '
        f'top={top_image_shape} wrist={wrist_image_shape}',
        flush=True,
    )

    # ── shared memory 연결 ───────────────────────────────────────────────────
    from multiprocessing.shared_memory import SharedMemory
    shm_obs = SharedMemory(name=args.shm_obs_name)
    shm_act = SharedMemory(name=args.shm_act_name)

    top_image_buffer = np.ndarray(
        top_image_shape, dtype=np.uint8, buffer=shm_obs.buf, offset=0
    )
    wrist_image_buffer = np.ndarray(
        wrist_image_shape, dtype=np.uint8, buffer=shm_obs.buf, offset=top_image_bytes
    )
    joint_state_buffer = np.ndarray(
        state_dimension,
        dtype=np.float32,
        buffer=shm_obs.buf,
        offset=top_image_bytes + wrist_image_bytes,
    )
    action_buffer = np.ndarray(
        (action_planes, action_chunk_size, action_dimension),
        dtype=np.float32,
        buffer=shm_act.buf,
    )

    # ── 모델 로딩 ────────────────────────────────────────────────────────────
    print(f'[act_policy_worker] Loading ACT from {args.model_path} on {args.device} ...', flush=True)
    model = ACTPolicy.from_pretrained(args.model_path)
    model.to(args.device)
    model.eval()
    device = torch.device(args.device)

    model_chunk = model.config.chunk_size
    if model_chunk > action_chunk_size:
        print(
            f'[act_policy_worker] WARNING: model chunk_size={model_chunk} '
            f'> configured chunk_size={action_chunk_size}. '
            f'memory.chunk_size를 act_serving_config.yaml에서 {model_chunk} 이상으로 늘려야 한다.',
            flush=True,
        )

    preprocess, postprocess = make_pre_post_processors(
        model.config,
        args.model_path,
        preprocessor_overrides={'device_processor': {'device': args.device}},
    )
    print(f'[act_policy_worker] Model loaded. chunk_size={model_chunk}', flush=True)

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
            inference_delay = struct.unpack('>I', receive_exactly(sock, 4))[0]

            top_image = top_image_buffer.copy()
            wrist_image = wrist_image_buffer.copy()
            joint_state = joint_state_buffer.copy()

            obs_dict = {
                'observation.images.top':   top_image,
                'observation.images.wrist': wrist_image,
                'observation.state':        joint_state,
            }
            observation = prepare_observation_for_inference(
                obs_dict, device, task=None, robot_type=args.robot_type
            )
            observation = preprocess(observation)

            with torch.no_grad():
                raw_action_chunk = model.predict_action_chunk(observation)

            original_chunk = raw_action_chunk.squeeze(0).clone()
            processed_chunk = postprocess(raw_action_chunk).squeeze(0)

            rows = min(len(processed_chunk.cpu().numpy()), action_chunk_size)
            action_buffer[:] = 0
            action_buffer[0, :rows] = original_chunk.cpu().numpy()[:rows]
            action_buffer[1, :rows] = processed_chunk.cpu().numpy()[:rows]

            sock.sendall(b'D')   # DONE

    shm_obs.close()
    shm_act.close()
    sock.close()
    print('[act_policy_worker] Shutdown.', flush=True)


if __name__ == '__main__':
    main()
