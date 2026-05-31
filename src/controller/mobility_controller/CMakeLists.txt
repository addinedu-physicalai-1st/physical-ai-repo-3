cmake_minimum_required(VERSION 3.8)
project(mobility_controller)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(mobility_controller_node src/mobility_controller_node.cpp)
ament_target_dependencies(mobility_controller_node rclcpp std_msgs)

install(TARGETS
  mobility_controller_node
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/scout_follow_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME scout_follow_controller
)

install(PROGRAMS
  scripts/scout_image_relay_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME scout_image_relay
)

install(DIRECTORY
  config
  launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
