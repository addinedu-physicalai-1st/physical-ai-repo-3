from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'debug_monitor'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Stephen Kong (gjkong)',
    maintainer_email='kong@pinklab.art',
    description='Read-only ROS topic monitor for Doby operational debugging.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'doby_debug_monitor = debug_monitor.debug_monitor_node:main',
        ],
    },
)
