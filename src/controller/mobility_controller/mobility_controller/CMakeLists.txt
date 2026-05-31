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

install(PROGRAMS
  scripts/approach_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME approach_controller
)

install(PROGRAMS
  scripts/nav_map_apply_adapter_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME nav_map_apply_adapter
)

install(PROGRAMS
  scripts/follow_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME follow_controller
)

install(PROGRAMS
  scripts/guiding_controller_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME guiding_controller
)

install(PROGRAMS
  scripts/patrol_scheduler_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME patrol_scheduler
)

install(PROGRAMS
  scripts/serving_dispatcher_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME serving_dispatcher
)

install(PROGRAMS
  scripts/table_markers_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME table_markers
)

install(PROGRAMS
  scripts/table_occupancy_detector_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME table_occupancy_detector
)

install(DIRECTORY
  config
  launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  find_package(ament_lint_auto REQUIRED)
  ament_add_pytest_test(test_scout_follow_control test/test_scout_follow_control.py)
  ament_add_pytest_test(test_patrol_scheduler test/test_patrol_scheduler.py)
  ament_add_pytest_test(test_guiding_controller test/test_guiding_controller.py)
  ament_add_pytest_test(test_table_occupancy_detector test/test_table_occupancy_detector.py)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
