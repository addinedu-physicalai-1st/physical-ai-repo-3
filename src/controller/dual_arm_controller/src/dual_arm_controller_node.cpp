#include <memory>
#include <string>

#include "controller_status_msgs/msg/status.hpp"
#include "rclcpp/rclcpp.hpp"

class DualArmControllerNode : public rclcpp::Node
{
public:
  DualArmControllerNode()
  : Node("dual_arm_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "dual_arm_controller");
    cooking_status_subscription_ = this->create_subscription<controller_status_msgs::msg::Status>(
      "/cooking_controller/status",
      10,
      [this](const controller_status_msgs::msg::Status::SharedPtr message) {
        RCLCPP_INFO(
          this->get_logger(),
          "dual_arm_controller received /cooking_controller/status: request_id=%u",
          message->request_id);
      });
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }

private:
  rclcpp::Subscription<controller_status_msgs::msg::Status>::SharedPtr cooking_status_subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<DualArmControllerNode>());
  rclcpp::shutdown();
  return 0;
}
