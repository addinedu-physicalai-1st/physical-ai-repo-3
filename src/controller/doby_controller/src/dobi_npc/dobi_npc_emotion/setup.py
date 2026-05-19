from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'dobi_npc_emotion'

setup(
    name=package_name,
    version='0.0.2',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # MediaPipe 모델 (scripts/download_models.sh가 채움)
        # face_landmarker.task (GEVA), efficientdet_lite0.tflite (person detector)
        (os.path.join('share', package_name, 'models'),
            glob('models/*.task') + glob('models/*.tflite')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Stephen Kong (gjkong)',
    maintainer_email='kong@pinklab.art',
    description='Dobi NPC emotion module — GEVA (face → V·A) [Phase 2 W4]',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'dummy_emotion_node = dobi_npc_emotion.dummy_emotion_node:main',
            'geva_node = dobi_npc_emotion.geva_node:main',
            'rapport_tracker = dobi_npc_emotion.rapport_tracker_node:main',
            'person_detector = dobi_npc_emotion.person_detector_node:main',
        ],
    },
)
