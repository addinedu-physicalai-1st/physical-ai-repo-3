#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"

class DualArmControllerNode : public rclcpp::Node
{
public:
  DualArmControllerNode()
  : Node("dual_arm_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "dual_arm_controller");
    cooking_status_subscription_ = this->create_subscription<std_msgs::msg::String>(
      "/cooking_controller/status",
      10,
      [this](const std_msgs::msg::String::SharedPtr message) {
        RCLCPP_INFO(
          this->get_logger(),
          "dual_arm_controller received /cooking_controller/status: %s",
          message->data.c_str());
      });
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }

private:
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr cooking_status_subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DualArmControllerNode>());
  rclcpp::shutdown();
  return 0;
}
