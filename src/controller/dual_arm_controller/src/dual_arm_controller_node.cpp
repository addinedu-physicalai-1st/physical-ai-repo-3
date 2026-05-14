#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"

class DualArmControllerNode : public rclcpp::Node
{
public:
  DualArmControllerNode()
  : Node("dual_arm_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "dual_arm_controller");
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DualArmControllerNode>());
  rclcpp::shutdown();
  return 0;
}
