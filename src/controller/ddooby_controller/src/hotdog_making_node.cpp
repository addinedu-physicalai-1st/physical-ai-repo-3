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

class HotdogMakingNode : public rclcpp::Node
{
public:
  HotdogMakingNode()
  : Node("ddooby_hotdog_making_node")
  {
    item_name_ = declare_parameter<std::string>("item_name", "new_york_hotdog");
    scenario_only_ = declare_parameter<bool>("scenario_only", true);
    step_delay_ms_ = declare_parameter<int>("step_delay_ms", 150);
  }

  bool runScenario()
  {
    RCLCPP_INFO(
      get_logger(),
      "Hotdog making task accepted: item=%s, scenario_only=%s",
      item_name_.c_str(),
      scenario_only_ ? "true" : "false");

    const std::vector<ScenarioStep> steps{
      {"case_pull", "right arm pulls the New York hotdog case horizontally from the right-side stack"},
      {"bread_pick", "right arm keeps holding the case while left arm picks bread from the handled bread tray"},
      {"bread_place", "left arm lowers bread from above and places it into the case"},
      {"sausage_pick", "left arm picks sausage from the handled sausage tray"},
      {"sausage_place", "left arm lowers sausage from above and places it on the bread"},
      {"ketchup_pick", "left arm picks the ketchup bottle from the right-side condiment area"},
      {"ketchup_aim", "left arm orients the ketchup nozzle toward the sausage over the case"},
      {"ketchup_squeeze", "left gripper slightly closes and moves horizontally along the sausage length"},
      {"pickup_place", "right arm places the completed New York hotdog at the pickup zone"},
    };

    for (size_t i = 0; i < steps.size(); ++i) {
      if (!rclcpp::ok()) {
        RCLCPP_WARN(get_logger(), "Hotdog task interrupted before step %zu", i + 1);
        return false;
      }
      RCLCPP_INFO(
        get_logger(),
        "Hotdog scenario step %zu/%zu [%s]: %s",
        i + 1,
        steps.size(),
        steps[i].name.c_str(),
        steps[i].description.c_str());
      sleepStep();
    }

    RCLCPP_INFO(get_logger(), "Hotdog task scenario completed");
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
  bool scenario_only_{true};
  int step_delay_ms_{150};
};
}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<HotdogMakingNode>();
  const bool success = node->runScenario();
  rclcpp::shutdown();
  return success ? 0 : 1;
}
