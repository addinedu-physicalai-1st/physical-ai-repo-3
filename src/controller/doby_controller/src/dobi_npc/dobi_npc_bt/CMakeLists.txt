cmake_minimum_required(VERSION 3.8)
project(dobi_npc_bt)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# 의존성
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(behaviortree_cpp REQUIRED)
find_package(dobi_npc_msgs REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(ament_index_cpp REQUIRED)

# 헤더 디렉토리
include_directories(include)

# Executor 실행 파일
add_executable(bt_executor src/bt_executor_node.cpp)
ament_target_dependencies(bt_executor
  rclcpp
  rclcpp_action
  behaviortree_cpp
  dobi_npc_msgs
  nav2_msgs
  geometry_msgs
  std_msgs
  sensor_msgs
  ament_index_cpp
)

# 설치
install(TARGETS bt_executor
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include/
)

install(DIRECTORY launch bt_xml config
  DESTINATION share/${PROJECT_NAME}/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_export_include_directories(include)
ament_package()
