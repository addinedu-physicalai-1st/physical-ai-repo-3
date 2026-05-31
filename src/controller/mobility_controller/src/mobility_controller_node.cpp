#include <memory>
#include <string>

#include "rclcpp/rclcpp.hpp"

class MobilityControllerNode : public rclcpp::Node
{
public:
  MobilityControllerNode()
  : Node("mobility_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "mobility_controller");
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<MobilityControllerNode>());
  rclcpp::shutdown();
  return 0;
}
