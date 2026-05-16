#include <memory>
#include <string>

#include "controller_status_msgs/msg/status.hpp"
#include "rclcpp/rclcpp.hpp"

class MobilityControllerNode : public rclcpp::Node
{
public:
  MobilityControllerNode()
  : Node("mobility_controller")
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "mobility_controller");
    serving_status_subscription_ = this->create_subscription<controller_status_msgs::msg::Status>(
      "/dobi_controller/status",
      10,
      [this](const controller_status_msgs::msg::Status::SharedPtr message) {
        RCLCPP_INFO(
          this->get_logger(),
          "mobility_controller received /dobi_controller/status: request_id=%u",
          message->request_id);
      });
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
  }

private:
  rclcpp::Subscription<controller_status_msgs::msg::Status>::SharedPtr serving_status_subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<MobilityControllerNode>());
  rclcpp::shutdown();
  return 0;
}
