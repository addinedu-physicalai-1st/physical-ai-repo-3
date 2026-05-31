import os
from pathlib import Path

from setuptools import find_packages, setup

package_name = 'dobi_npc_minigame'


def collect_data_files(source_root: str, install_root: str):
    entries = []
    setup_dir = Path(__file__).resolve().parent
    root = (setup_dir / source_root).resolve()
    if not root.is_dir():
        return entries
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name != '__pycache__' and not name.startswith('.')
        ]
        files = [
            os.path.relpath(Path(dirpath) / filename, setup_dir)
            for filename in filenames
            if not filename.endswith(('.pyc', '.pyo'))
        ]
        if not files:
            continue
        rel_dir = Path(dirpath).relative_to(root)
        install_dir = os.path.join('share', package_name, install_root)
        if str(rel_dir) != '.':
            install_dir = os.path.join(install_dir, str(rel_dir))
        entries.append((
            install_dir,
            files,
        ))
    return entries


setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ] + collect_data_files('../../../games', 'games'),
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
