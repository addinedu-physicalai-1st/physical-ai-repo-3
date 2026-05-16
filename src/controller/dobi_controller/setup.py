from glob import glob
from setuptools import find_packages, setup

package_name = 'dobi_controller'

setup(
    name=package_name,
    version='0.0.0',
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
    maintainer='robo',
    maintainer_email='robo@example.com',
    description='ROS2 Python package scaffold for the dobi controller.',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'dobi_controller_node = dobi_controller.dobi_controller_node:main',
        ],
    },
)
