from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'dobi_npc_bringup'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'models', 'yolo'), glob('models/yolo/*.pt')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Stephen Kong (gjkong)',
    maintainer_email='kong@pinklab.art',
    description='Integration launch files for the dobi_npc system',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fake_customer_publisher = dobi_npc_bringup.fake_customer_publisher:main',
            'mode_manager = dobi_npc_bringup.mode_manager_node:main',
            'mode_stack_stub = dobi_npc_bringup.mode_stack_stub:main',
            'follow_controller = dobi_npc_bringup.follow_controller_node:main',
            'serving_dispatcher = dobi_npc_bringup.serving_dispatcher_node:main',
            'patrol_scheduler = dobi_npc_bringup.patrol_scheduler_node:main',
            'table_occupancy_detector = dobi_npc_bringup.table_occupancy_detector_node:main',
            'guiding_controller = dobi_npc_bringup.guiding_controller_node:main',
            'map_apply = dobi_npc_bringup.map_apply_node:main',
        ],
    },
)
