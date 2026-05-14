#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"

class CookingControllerNode : public rclcpp::Node
{
public:
  CookingControllerNode()
  : Node("cooking_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "cooking_controller");
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<CookingControllerNode>());
  rclcpp::shutdown();
  return 0;
}
