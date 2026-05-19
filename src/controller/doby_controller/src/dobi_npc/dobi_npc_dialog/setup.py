from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'dobi_npc_dialog'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'config', 'personas'),
            glob('config/personas/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Stephen Kong (gjkong)',
    maintainer_email='kong@pinklab.art',
    description='Dobi NPC dialog module — persona manager + phrase pool',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'dummy_dialog_node = dobi_npc_dialog.dummy_dialog_node:main',
            'persona_manager = dobi_npc_dialog.persona_manager_node:main',
            'face_avatar = dobi_npc_dialog.face_avatar_node:main',
            'tts_node = dobi_npc_dialog.tts_node:main',
            'dialog_router = dobi_npc_dialog.dialog_router_node:main',
        ],
    },
)
