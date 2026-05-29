from glob import glob

from setuptools import find_packages, setup

package_name = 'dobi_gimbal'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/firmware/dobi_gimbal',
            glob('firmware/dobi_gimbal/*.ino')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jin',
    maintainer_email='rlawlsdn4665@gmail.com',
    description='Pan-tilt gimbal Arduino serial bridge for the dobi docking feature.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            f'gimbal_bridge_node = {package_name}.gimbal_bridge_node:main',
        ],
    },
)
