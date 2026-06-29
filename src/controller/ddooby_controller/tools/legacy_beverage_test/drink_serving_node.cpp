#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>

namespace
{
using namespace std::chrono_literals;

struct ScenarioStep
{
  std::string name;
  std::string description;
};

class DrinkServingNode : public rclcpp::Node
{
public:
  DrinkServingNode()
  : Node("ddooby_drink_serving_node")
  {
    item_name_ = declare_parameter<std::string>("item_name", "drink");
    drink_model_ = declare_parameter<std::string>("drink_model", "coffee");
    scenario_only_ = declare_parameter<bool>("scenario_only", true);
    step_delay_ms_ = declare_parameter<int>("step_delay_ms", 150);
  }

  bool runScenario()
  {
    RCLCPP_INFO(
      get_logger(),
      "Drink serving task accepted: item=%s, drink_model=%s, scenario_only=%s",
      item_name_.c_str(),
      drink_model_.c_str(),
      scenario_only_ ? "true" : "false");

    const std::vector<ScenarioStep> steps{
      {"fridge_open", "right hand opens the refrigerator door"},
      {"drink_pick", "right hand picks the requested drink from the configured refrigerator slot"},
      {"pickup_place", "right hand places the drink at the pickup zone"},
    };

    for (size_t i = 0; i < steps.size(); ++i) {
      if (!rclcpp::ok()) {
        RCLCPP_WARN(get_logger(), "Drink serving task interrupted before step %zu", i + 1);
        return false;
      }
      RCLCPP_INFO(
        get_logger(),
        "Drink scenario step %zu/%zu [%s]: %s",
        i + 1,
        steps.size(),
        steps[i].name.c_str(),
        steps[i].description.c_str());
      sleepStep();
    }

    RCLCPP_INFO(get_logger(), "Drink serving scenario completed");
    return true;
  }

private:
  void sleepStep() const
  {
    if (step_delay_ms_ > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(step_delay_ms_));
    }
  }

  std::string item_name_;
  std::string drink_model_;
  bool scenario_only_{true};
  int step_delay_ms_{150};
};
}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<DrinkServingNode>();
  const bool success = node->runScenario();
  rclcpp::shutdown();
  return success ? 0 : 1;
}
