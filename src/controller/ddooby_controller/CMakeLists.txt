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


add_executable(manifacture_action_server_node src/manifacture_action_server_node.cpp)
ament_target_dependencies(manifacture_action_server_node
  rclcpp
  rclcpp_action
  custom_msg
)

add_library(ddooby_manufacturing_task_core STATIC
  src/task/manufacturing_beverage_task.cpp
  src/task/manufacturing_completed_hotdog_task.cpp
  src/task/manufacturing_hotdog_steps.cpp
  src/task/manufacturing_ketchup_task.cpp
  src/task/manufacturing_pick_planner.cpp
  src/task/manufacturing_pick_execution.cpp
  src/task/manufacturing_place_planner.cpp
  src/task/manufacturing_pose_utils.cpp
  src/task/manufacturing_result_validation.cpp
  src/task/manufacturing_result_validator.cpp
  src/task/manufacturing_task_assembly.cpp
  src/task/manufacturing_task_common.cpp
  src/task/manufacturing_task_runtime.cpp
  src/task/manufacturing_task_sequence_runner.cpp
  src/control/manufacturing_motion_primitives.cpp
  src/control/manufacturing_stage_motion.cpp
  src/control/moveit_task_utils.cpp
  src/control/planning_scene_utils.cpp
  src/simulator/manufacturing_layout_utils.cpp
  src/simulator/manufacturing_target_loading.cpp
  src/manufacturing_task_runner.cpp
  src/vision/vision_pick_adapter.cpp
  src/vision/vision_pick_detection_store.cpp
)
target_include_directories(ddooby_manufacturing_task_core
  PUBLIC include
  PRIVATE src
)
ament_target_dependencies(ddooby_manufacturing_task_core
  ament_index_cpp
  geometry_msgs
  moveit_ros_planning_interface
  moveit_msgs
  rclcpp
  shape_msgs
  vision_msgs
)

add_executable(hotdog_making_node src/hotdog_making_node.cpp)
target_include_directories(hotdog_making_node PRIVATE
  include
)
target_link_libraries(hotdog_making_node
  ddooby_manufacturing_task_core
)

add_executable(forward_joint_trajectory_bridge_node src/control/forward_joint_trajectory_bridge_node.cpp)
ament_target_dependencies(forward_joint_trajectory_bridge_node
  control_msgs
  rclcpp
  rclcpp_action
  sensor_msgs
  std_msgs
  trajectory_msgs
)

install(TARGETS
  forward_joint_trajectory_bridge_node
  hotdog_making_node
  manifacture_action_server_node
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/capture_gazebo_yolo_dataset.py
  scripts/gazebo_yolo_pose_node.py
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
