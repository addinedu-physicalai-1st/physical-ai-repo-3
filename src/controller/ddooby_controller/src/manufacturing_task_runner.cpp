#include <memory>
#include <thread>

#include <rclcpp/rclcpp.hpp>

#include "ddooby_controller/manufacturing_task_runner.hpp"
#include "manufacturing_task_node.hpp"

namespace ddooby_controller
{

int runHotdogMakingNode(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<HotdogMakingNode>();

  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() { executor.spin(); });

  const bool success = node->run();
  rclcpp::shutdown();
  if (spinner.joinable()) {
    spinner.join();
  }
  return success ? 0 : 1;
}

}  // namespace ddooby_controller
