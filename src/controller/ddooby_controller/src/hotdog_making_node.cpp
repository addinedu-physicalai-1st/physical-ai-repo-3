#include <memory>
#include <thread>

#include <rclcpp/rclcpp.hpp>

#include "manufacturing_task_node_private.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<ddooby_controller::HotdogMakingNode>();

  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() { executor.spin(); });

  const bool success = node->run();
  executor.cancel();
  if (spinner.joinable()) {
    spinner.join();
  }
  executor.remove_node(node);
  node.reset();
  rclcpp::shutdown();
  return success ? 0 : 1;
}
