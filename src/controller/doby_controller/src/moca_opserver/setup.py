import os
from glob import glob
from setuptools import setup

package_name = 'moca_opserver'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
        # 정적 자산 (대시보드 — moca_web_dashboard_spec.md)
        (os.path.join('share', package_name, 'static'),
            glob('static/*.html')),
        (os.path.join('share', package_name, 'static', 'pages'),
            glob('static/pages/*.html')),
        (os.path.join('share', package_name, 'static', 'components'),
            glob('static/components/*.js')),
        (os.path.join('share', package_name, 'static', 'js'),
            glob('static/js/*.js')),
        (os.path.join('share', package_name, 'static', 'css'),
            glob('static/css/*.css')),
        (os.path.join('share', package_name, 'static', 'assets'),
            glob('static/assets/*.svg') + glob('static/assets/*.png')),
        (os.path.join('share', package_name, 'static', 'assets', 'icons'),
            glob('static/assets/icons/*.svg')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Stephen Kong (gjkong)',
    maintainer_email='kong@pinklab.art',
    description='moca operations server (REST + WebSocket + ROS2 bridge) for 5-state FSM.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'opserver_node = moca_opserver.opserver_node:main',
        ],
    },
)
