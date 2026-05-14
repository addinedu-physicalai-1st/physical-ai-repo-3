#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"

class VicPinkyControllerNode : public rclcpp::Node
{
public:
  VicPinkyControllerNode()
  : Node("vic_pinky_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "vic_pinky_controller");
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<VicPinkyControllerNode>());
  rclcpp::shutdown();
  return 0;
}
