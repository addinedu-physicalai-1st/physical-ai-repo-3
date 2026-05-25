cmake_minimum_required(VERSION 3.8)
project(dobi_npc_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/EmotionState.msg"
  "msg/RapportEvent.msg"
  "msg/MinigameResult.msg"
  "msg/UtterRequest.msg"
  "msg/ModeState.msg"
  "msg/PatrolState.msg"
  "msg/TableReport.msg"
  "msg/GuidingState.msg"
  "msg/OpEvent.msg"
  "msg/OperatorCommand.msg"
  "msg/PersonTrack.msg"
  "msg/PersonTrackArray.msg"
  "srv/SetPersona.srv"
  "srv/SetMode.srv"
  "srv/GetTableStatus.srv"
  "srv/SetPatrolSchedule.srv"
  "srv/ScanTable.srv"
  DEPENDENCIES std_msgs builtin_interfaces sensor_msgs
)

ament_export_dependencies(rosidl_default_runtime)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
