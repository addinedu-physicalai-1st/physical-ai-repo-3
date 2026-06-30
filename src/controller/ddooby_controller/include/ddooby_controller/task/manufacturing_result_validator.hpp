#pragma once

#include <map>
#include <optional>
#include <string>

#include <Eigen/Geometry>
#include <rclcpp/logger.hpp>

#include "ddooby_controller/task/manufacturing_task_presets.hpp"
#include "ddooby_controller/task/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

struct ManufacturingResultValidatorConfig
{
  bool enabled{false};
  bool dry_run{false};
  bool has_partial_stage_limit{false};
  bool has_partial_waypoint_limit{false};
  int settle_ms{1000};
  double hotdog_item_xy_tolerance_m{0.18};
  double ketchup_return_xy_tolerance_m{0.08};
  double ketchup_return_z_tolerance_m{0.08};
  double beverage_pickup_xy_tolerance_m{0.35};
  std::string package_share_directory;
  std::string layout_path;
  std::string case_target_model{"case"};
  std::string bread_target_model{"bread1"};
  std::string sausage_target_model{"sausage"};
  std::string ketchup_target_model{"kachup"};
  std::string coke_target_model{"can_coke"};
  std::string coffee_target_model{"can_coffee"};
  std::string target_model{"auto"};
};

class ManufacturingResultValidator
{
public:
  ManufacturingResultValidator(
    const rclcpp::Logger & logger,
    ManufacturingResultValidatorConfig config);

  bool shouldValidate() const;
  std::optional<std::map<std::string, Eigen::Vector3d>> readGazeboModelPositions() const;
  bool validateHotdogPlacement();
  bool validateBeveragePlacement(task_presets::ManufacturingTarget beverage_target);

private:
  bool loadTarget(const std::string & target_model, TargetObject & target) const;

  rclcpp::Logger logger_;
  ManufacturingResultValidatorConfig config_;
};

}  // namespace ddooby_controller::manufacturing_task
