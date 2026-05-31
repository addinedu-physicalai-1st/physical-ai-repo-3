from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'person_tracking_pkg'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.py')),
        (os.path.join('share', package_name, 'models'),
            glob('models/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='soon',
    maintainer_email='shanj0207@gmail.com',
    description='Person tracking — YOLOv8 + DBSCAN + BoT-SORT + MediaPipe Pose',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'person_tracking_node = person_tracking_pkg.person_tracking_node:main',
            'group_approach_node = person_tracking_pkg.group_approach_node:main',
        ],
    },
)
