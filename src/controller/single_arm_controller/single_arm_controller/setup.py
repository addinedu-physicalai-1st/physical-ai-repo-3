from setuptools import find_packages, setup

package_name = 'single_arm_controller'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', [
            'launch/act_serving.launch.py',
            'launch/single_arm_controller.launch.py',
        ]),
        ('share/' + package_name + '/config', [
            'config/single_arm_controller.yaml',
            'config/act_serving_config.yaml',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='jr',
    maintainer_email='jay960311@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'act_policy_server = single_arm_controller.act_policy_server:main',
            'act_serving_controller = single_arm_controller.act_serving_action_server:main',
            'controller_status_monitor = single_arm_controller.controller_status_monitor:main',
        ],
    },
)
