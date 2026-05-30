from glob import glob

from setuptools import find_packages, setup

package_name = 'dobi_dock'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jin',
    maintainer_email='rlawlsdn4665@gmail.com',
    description='Left-side table docking: depth table-edge perception, lidar safety and dock controller.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            f'dock_perception_node = {package_name}.dock_perception_node:main',
        ],
    },
)
