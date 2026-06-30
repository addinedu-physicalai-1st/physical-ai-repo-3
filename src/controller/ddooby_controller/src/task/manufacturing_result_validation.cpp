#include "manufacturing_task_node_private.hpp"

#include "ddooby_controller/task/manufacturing_result_validator.hpp"

namespace ddooby_controller
{

using manufacturing_task::ManufacturingResultValidator;
using manufacturing_task::ManufacturingResultValidatorConfig;

bool HotdogMakingNode::shouldValidateGazeboResult() const
{
  return validate_gazebo_result_ &&
         !dry_run_ &&
         !play_to_stage_.has_value() &&
         play_to_waypoint_.empty();
}

bool HotdogMakingNode::validateFinalHotdogPlacement()
{
  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }
  ManufacturingResultValidator validator(
    get_logger(),
    ManufacturingResultValidatorConfig{
      validate_gazebo_result_,
      dry_run_,
      play_to_stage_.has_value(),
      !play_to_waypoint_.empty(),
      result_validation_settle_ms_,
      result_validation_hotdog_item_xy_tolerance_m_,
      result_validation_ketchup_return_xy_tolerance_m_,
      result_validation_ketchup_return_z_tolerance_m_,
      result_validation_beverage_pickup_xy_tolerance_m_,
      package_share_directory,
      layout_path_,
      case_target_model_,
      bread_target_model_,
      sausage_target_model_,
      ketchup_target_model_,
      coke_target_model_,
      coffee_target_model_,
      target_model_});
  return validator.validateHotdogPlacement();
}

bool HotdogMakingNode::validateFinalBeveragePlacement(ManufacturingTarget beverage_target)
{
  std::string package_share_directory;
  if (!resolvePackageShareDirectory(package_share_directory)) {
    return false;
  }
  ManufacturingResultValidator validator(
    get_logger(),
    ManufacturingResultValidatorConfig{
      validate_gazebo_result_,
      dry_run_,
      play_to_stage_.has_value(),
      !play_to_waypoint_.empty(),
      result_validation_settle_ms_,
      result_validation_hotdog_item_xy_tolerance_m_,
      result_validation_ketchup_return_xy_tolerance_m_,
      result_validation_ketchup_return_z_tolerance_m_,
      result_validation_beverage_pickup_xy_tolerance_m_,
      package_share_directory,
      layout_path_,
      case_target_model_,
      bread_target_model_,
      sausage_target_model_,
      ketchup_target_model_,
      coke_target_model_,
      coffee_target_model_,
      target_model_});
  return validator.validateBeveragePlacement(beverage_target);
}

}  // namespace ddooby_controller
