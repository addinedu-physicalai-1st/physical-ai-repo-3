#!/usr/bin/env python3
"""
ACT policy inference ROS node.

This node owns the ACT model runtime. It exchanges large observation/action
arrays through shared memory and uses a small ROS service only as the inference
trigger/completion signal.
"""

from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

import numpy as np
import rclpy as rp
from rclpy.node import Node
import torch
import yaml

from lerobot.policies.act import ACTPolicy
from lerobot.policies import make_pre_post_processors
from lerobot.policies.utils import prepare_observation_for_inference
from single_arm_controller_interfaces.srv import ActPolicyInference


_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / 'config' / 'act_serving_config.yaml')


def load_act_serving_config(path: str) -> dict:
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def create_owned_shared_memory(name: str, size: int) -> SharedMemory:
    try:
        return SharedMemory(name=name, create=True, size=size)
    except FileExistsError:
        stale = SharedMemory(name=name)
        stale.unlink()
        stale.close()
        return SharedMemory(name=name, create=True, size=size)


class ActPolicyServer(Node):
    def __init__(self):
        super().__init__('act_policy_server')
        self.declare_parameter('config_path', _DEFAULT_CONFIG_PATH)

        config_path = self.get_parameter('config_path').value
        self.get_logger().info(f'Loading ACT serving config: {config_path}')
        self._config = load_act_serving_config(config_path)

        self._init_shared_memory()
        self._load_model()

        service_name = self._config.get('ipc', {}).get('service_name', '/act_policy/infer')
        self._service = self.create_service(
            ActPolicyInference,
            service_name,
            self.handle_inference_request,
        )
        self.get_logger().info(f'ACT policy server ready: {service_name}')

    def _init_shared_memory(self):
        memory_config = self._config['memory']
        ipc_config = self._config.get('ipc', {})

        self._top_image_shape = tuple(memory_config['top_shape'])
        self._wrist_image_shape = tuple(memory_config['wrist_shape'])
        self._state_dimension = int(memory_config['state_dim'])
        self._action_chunk_size = int(memory_config['chunk_size'])
        self._action_dimension = int(memory_config['action_dim'])

        self._top_image_bytes = int(np.prod(self._top_image_shape))
        self._wrist_image_bytes = int(np.prod(self._wrist_image_shape))
        self._state_bytes = self._state_dimension * 4
        self._obs_bytes = self._top_image_bytes + self._wrist_image_bytes + self._state_bytes
        self._act_planes = 2
        self._act_bytes = self._act_planes * self._action_chunk_size * self._action_dimension * 4

        obs_name = ipc_config.get('shm_obs_name', 'act_policy_observation')
        act_name = ipc_config.get('shm_act_name', 'act_policy_action')
        self._shm_obs = create_owned_shared_memory(obs_name, self._obs_bytes)
        self._shm_act = create_owned_shared_memory(act_name, self._act_bytes)

        self._top_image_buffer = np.ndarray(
            self._top_image_shape, dtype=np.uint8, buffer=self._shm_obs.buf, offset=0
        )
        self._wrist_image_buffer = np.ndarray(
            self._wrist_image_shape,
            dtype=np.uint8,
            buffer=self._shm_obs.buf,
            offset=self._top_image_bytes,
        )
        self._joint_state_buffer = np.ndarray(
            self._state_dimension,
            dtype=np.float32,
            buffer=self._shm_obs.buf,
            offset=self._top_image_bytes + self._wrist_image_bytes,
        )
        self._action_buffer = np.ndarray(
            (self._act_planes, self._action_chunk_size, self._action_dimension),
            dtype=np.float32,
            buffer=self._shm_act.buf,
        )

        self.get_logger().info(
            f'Shared memory ready: obs={obs_name} ({self._obs_bytes} bytes), '
            f'act={act_name} ({self._act_bytes} bytes)'
        )

    def _load_model(self):
        model_config = self._config['model']
        self._device = torch.device(model_config['device'])
        self._robot_type = model_config['robot_type']

        self.get_logger().info(
            f"Loading ACT model: {model_config['path']} on {model_config['device']}"
        )
        self._model = ACTPolicy.from_pretrained(model_config['path'])
        self._model.to(self._device)
        self._model.eval()

        model_chunk = self._model.config.chunk_size
        if model_chunk > self._action_chunk_size:
            self.get_logger().warn(
                f'model chunk_size={model_chunk} > configured '
                f'chunk_size={self._action_chunk_size}. Increase memory.chunk_size.'
            )

        self._preprocess, self._postprocess = make_pre_post_processors(
            self._model.config,
            model_config['path'],
            preprocessor_overrides={'device_processor': {'device': model_config['device']}},
        )
        self.get_logger().info(f'ACT model loaded. chunk_size={model_chunk}')

    def handle_inference_request(self, request, response):
        del request  # Inference delay is reserved for future RTC-aware model APIs.
        try:
            top_image = self._top_image_buffer.copy()
            wrist_image = self._wrist_image_buffer.copy()
            joint_state = self._joint_state_buffer.copy()

            obs_dict = {
                'observation.images.top': top_image,
                'observation.images.wrist': wrist_image,
                'observation.state': joint_state,
            }
            observation = prepare_observation_for_inference(
                obs_dict,
                self._device,
                task=None,
                robot_type=self._robot_type,
            )
            observation = self._preprocess(observation)

            with torch.no_grad():
                raw_action_chunk = self._model.predict_action_chunk(observation)

            original_chunk = raw_action_chunk.squeeze(0).clone()
            processed_chunk = self._postprocess(raw_action_chunk).squeeze(0)

            original_np = original_chunk.cpu().numpy()
            processed_np = processed_chunk.cpu().numpy()
            rows = min(len(processed_np), self._action_chunk_size)

            self._action_buffer[:] = 0
            self._action_buffer[0, :rows] = original_np[:rows]
            self._action_buffer[1, :rows] = processed_np[:rows]

            response.success = True
            response.message = f'inference complete rows={rows}'
        except Exception as e:
            self.get_logger().error(f'ACT inference failed: {e}')
            response.success = False
            response.message = str(e)
        return response

    def destroy_node(self):
        for shm in (self._shm_obs, self._shm_act):
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
            shm.close()
        super().destroy_node()


def main(args=None):
    rp.init(args=args)
    node = ActPolicyServer()
    try:
        rp.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rp.shutdown()


if __name__ == '__main__':
    main()
