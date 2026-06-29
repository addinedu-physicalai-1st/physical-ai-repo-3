#include "ddooby_controller/manufacturing_task_sequence_runner.hpp"

#include "ddooby_controller/manufacturing_task_common.hpp"

#include <rclcpp/rclcpp.hpp>

namespace ddooby_controller::manufacturing_task
{

TaskSequenceRunner::TaskSequenceRunner(const rclcpp::Logger & logger)
: logger_(logger)
{
}

bool TaskSequenceRunner::runHotdogAssembly(
  task_presets::ManufacturingTarget endpoint,
  const std::vector<HotdogAssemblyStep> & steps,
  const std::function<bool()> & run_completed_hotdog_place,
  const std::function<bool()> & return_left_arm_home_if_needed,
  const std::function<bool()> & validate_result)
{
  const int endpoint_order = hotdogAssemblyStepOrder(endpoint);
  if (endpoint_order <= 0) {
    RCLCPP_ERROR(
      logger_,
      "Unsupported hotdog assembly endpoint: %s",
      task_presets::targetName(endpoint));
    return false;
  }

  RCLCPP_INFO(
    logger_,
    "New York hotdog assembly started: endpoint=%s",
    task_presets::targetName(endpoint));

  for (std::size_t index = 0; index < steps.size(); ++index) {
    const auto & step = steps[index];
    RCLCPP_INFO(
      logger_,
      "Hotdog assembly step %zu/5: %s (%s)",
      index + 1,
      step.description.c_str(),
      step.model_name.c_str());
    if (!step.run()) {
      return false;
    }

    if (endpoint_order == hotdogAssemblyStepOrder(step.target)) {
      RCLCPP_INFO(
        logger_,
        "New York hotdog assembly stopped at %s endpoint",
        task_presets::targetName(step.target));
      return true;
    }
  }

  RCLCPP_INFO(logger_, "Hotdog assembly step 5/5: place completed hotdog at pickup zone");
  if (!run_completed_hotdog_place()) {
    return false;
  }
  if (!return_left_arm_home_if_needed()) {
    return false;
  }
  if (!validate_result()) {
    return false;
  }

  RCLCPP_INFO(logger_, "New York hotdog assembly completed");
  return true;
}

}  // namespace ddooby_controller::manufacturing_task
