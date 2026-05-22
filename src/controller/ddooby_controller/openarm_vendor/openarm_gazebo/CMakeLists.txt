cmake_minimum_required(VERSION 3.8)
project(openarm_gazebo)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config launch urdf worlds
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS scripts/gripper_mimic_follower.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
