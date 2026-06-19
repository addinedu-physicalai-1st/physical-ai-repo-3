cmake_minimum_required(VERSION 3.8)
project(ddooby_controller)

find_package(ament_cmake REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(control_msgs REQUIRED)
find_package(custom_msg REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(moveit_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(shape_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(vision_msgs REQUIRED)
find_package(gz-msgs10 REQUIRED)
find_package(gz-transport13 REQUIRED)
find_package(ros_gz_interfaces REQUIRED)


add_executable(manifacture_action_server_node src/manifacture_action_server_node.cpp)
ament_target_dependencies(manifacture_action_server_node
  rclcpp
  rclcpp_action
  custom_msg
)

add_executable(hotdog_making_node src/hotdog_making_node.cpp)
target_include_directories(hotdog_making_node PRIVATE
  include
)
ament_target_dependencies(hotdog_making_node
  ament_index_cpp
  geometry_msgs
  moveit_ros_planning_interface
  moveit_msgs
  rclcpp
  shape_msgs
  vision_msgs
)

add_executable(drink_serving_node src/drink_serving_node.cpp)
ament_target_dependencies(drink_serving_node
  rclcpp
)

add_executable(forward_joint_trajectory_bridge_node src/forward_joint_trajectory_bridge_node.cpp)
ament_target_dependencies(forward_joint_trajectory_bridge_node
  control_msgs
  rclcpp
  rclcpp_action
  sensor_msgs
  std_msgs
  trajectory_msgs
)

add_executable(beverage_making_test_node src/beverage_making_test_node.cpp)
ament_target_dependencies(beverage_making_test_node
  rclcpp
  trajectory_msgs
  moveit_ros_planning_interface
  ros_gz_interfaces
)
target_link_libraries(beverage_making_test_node
  gz-msgs10::core
  gz-transport13::core
)

install(TARGETS
  beverage_making_test_node
  drink_serving_node
  forward_joint_trajectory_bridge_node
  hotdog_making_node
  manifacture_action_server_node
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/capture_gazebo_yolo_dataset.py
  scripts/gazebo_yolo_pose_node.py
  scripts/realsense_hsv_preview.py
  scripts/sync_planning_scene_from_layout.py
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  launch
  assets
  DESTINATION share/${PROJECT_NAME}
)

install(DIRECTORY
  include/
  DESTINATION include
)

ament_package()
