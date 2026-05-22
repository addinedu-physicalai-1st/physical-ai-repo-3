cmake_minimum_required(VERSION 3.8)
project(ddooby_controller)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(gz-msgs10 REQUIRED)
find_package(gz-transport13 REQUIRED)

add_executable(beverage_making_test_node src/beverage_making_test_node.cpp)
ament_target_dependencies(beverage_making_test_node
  rclcpp
  trajectory_msgs
  moveit_ros_planning_interface
)
target_link_libraries(beverage_making_test_node
  gz-msgs10::core
  gz-transport13::core
)

install(TARGETS
  beverage_making_test_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  launch
  models
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
