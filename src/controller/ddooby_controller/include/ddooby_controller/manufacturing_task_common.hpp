#pragma once

#include <optional>
#include <string>
#include <vector>

#include "ddooby_controller/manufacturing_task_presets.hpp"
#include "ddooby_controller/manufacturing_task_types.hpp"

namespace ddooby_controller::manufacturing_task
{

namespace task_presets = ddooby_controller::manufacturing_task_presets;

std::string normalizeStageName(const std::string & value);

std::optional<task_presets::ManufacturingStage> parsePlayToStage(const std::string & value);

task_presets::ManufacturingTarget parseManufacturingTask(const std::string & value);

std::optional<task_presets::ArmSide> parseArmSide(const std::string & value);

std::string selectTargetModelOverride(
  const std::string & requested_model,
  const std::string & default_model);

task_presets::ArmSide defaultArmForTarget(task_presets::ManufacturingTarget target);

bool isHotdogAssemblyEndpoint(task_presets::ManufacturingTarget target);

bool isBeverageTarget(task_presets::ManufacturingTarget target);

double beveragePickupZoneYOffset(task_presets::ManufacturingTarget beverage_target);

std::string beverageTargetModel(
  task_presets::ManufacturingTarget beverage_target,
  const std::string & requested_model,
  const std::string & coffee_target_model,
  const std::string & coke_target_model);

int hotdogAssemblyStepOrder(task_presets::ManufacturingTarget target);

std::optional<task_presets::ManufacturingStage> stageEndpointFromWaypointName(
  const std::string & value);

std::optional<task_presets::ManufacturingStage> stageHintFromWaypointName(
  const std::string & value);

int stageOrder(task_presets::ManufacturingStage stage);

bool shouldRunManufacturingStage(
  task_presets::ManufacturingStage stage,
  task_presets::ManufacturingStage start_stage);

bool shouldStopAtOrBeforeStage(
  const std::optional<task_presets::ManufacturingStage> & play_to_stage,
  task_presets::ManufacturingStage stage);

bool shouldStopAtOrBeforeWaypointStage(
  const std::string & play_to_waypoint,
  task_presets::ManufacturingStage stage);

bool stopWaypointMatches(
  const std::string & play_to_waypoint,
  task_presets::ManufacturingStage stage,
  const std::string & waypoint);

std::vector<ScenarioStep> makeHotdogScenarioSteps();

}  // namespace ddooby_controller::manufacturing_task
