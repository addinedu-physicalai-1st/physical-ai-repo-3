#pragma once

#include <functional>
#include <string>
#include <vector>

#include <rclcpp/logger.hpp>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

struct HotdogAssemblyStep
{
  task_presets::ManufacturingTarget target;
  std::string model_name;
  std::string description;
  std::function<bool()> run;
};

class TaskSequenceRunner
{
public:
  explicit TaskSequenceRunner(const rclcpp::Logger & logger);

  bool runHotdogAssembly(
    task_presets::ManufacturingTarget endpoint,
    const std::vector<HotdogAssemblyStep> & steps,
    const std::function<bool()> & run_completed_hotdog_place,
    const std::function<bool()> & return_left_arm_home_if_needed,
    const std::function<bool()> & validate_result);

private:
  rclcpp::Logger logger_;
};

}  // namespace ddooby_controller::manufacturing_task
