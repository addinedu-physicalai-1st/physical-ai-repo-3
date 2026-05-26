cmake_minimum_required(VERSION 3.8)
project(mobility_controller)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(controller_status_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(mobility_controller_node src/mobility_controller_node.cpp)
ament_target_dependencies(mobility_controller_node controller_status_msgs rclcpp std_msgs)

install(TARGETS
  mobility_controller_node
  DESTINATION lib/${PROJECT_NAME}
)

# 주행 제어 Python 노드 설치 (approach / follow)
install(PROGRAMS scripts/approach_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME approach_controller_node)

install(PROGRAMS scripts/follow_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME follow_controller_node)

install(PROGRAMS scripts/camera_pan_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME camera_pan_controller_node)

install(DIRECTORY
  config
  launch
  scripts
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
