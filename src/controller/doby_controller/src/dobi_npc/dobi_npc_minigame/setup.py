from setuptools import find_packages, setup

package_name = 'dobi_npc_minigame'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Stephen Kong (gjkong)',
    maintainer_email='kong@pinklab.art',
    description='Dobi NPC minigame module (RPS Phase 3)',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'dummy_minigame_node = dobi_npc_minigame.dummy_minigame_node:main',
            'minigame_runner = dobi_npc_minigame.minigame_runner_node:main',
        ],
    },
)
