#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"

class VicPinkyControllerNode : public rclcpp::Node
{
public:
  VicPinkyControllerNode()
  : Node("vic_pinky_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "vic_pinky_controller");
    serving_status_subscription_ = this->create_subscription<std_msgs::msg::String>(
      "/serving_controller/status",
      10,
      [this](const std_msgs::msg::String::SharedPtr message) {
        RCLCPP_INFO(
          this->get_logger(),
          "vic_pinky_controller received /serving_controller/status: %s",
          message->data.c_str());
      });
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }

private:
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr serving_status_subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<VicPinkyControllerNode>());
  rclcpp::shutdown();
  return 0;
}
