#include "ddooby_controller/task/manufacturing_task_common.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <vector>

namespace ddooby_controller::manufacturing_task
{

std::string normalizeStageName(const std::string & value)
{
  std::string normalized;
  normalized.reserve(value.size());
  for (char character : value) {
    if (character == '_' || character == '-' || character == ' ' ||
      character == '.' || character == '/' || character == ':')
    {
      continue;
    }
    normalized.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(character))));
  }
  return normalized;
}

bool parsePlayToStage(const std::string & value, task_presets::ManufacturingStage & stage)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized.empty() || normalized == "complete" || normalized == "all" ||
    normalized == "none")
  {
    return false;
  }
  if (normalized == "home") {
    stage = task_presets::ManufacturingStage::Home;
    return true;
  }
  if (normalized == "pick") {
    stage = task_presets::ManufacturingStage::Pick;
    return true;
  }
  if (normalized == "work") {
    stage = task_presets::ManufacturingStage::Work;
    return true;
  }
  if (normalized == "place") {
    stage = task_presets::ManufacturingStage::Place;
    return true;
  }
  if (normalized == "returnhome") {
    stage = task_presets::ManufacturingStage::ReturnHome;
    return true;
  }
  if (normalized == "pregrasp" || normalized == "pullout") {
    stage = task_presets::ManufacturingStage::Pick;
    return true;
  }
  throw std::invalid_argument("unsupported play_to_stage '" + value + "'");
}

task_presets::ManufacturingTarget parseManufacturingTask(const std::string & value)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized == "bread") {
    return task_presets::ManufacturingTarget::Bread;
  }
  if (normalized == "case") {
    return task_presets::ManufacturingTarget::Case;
  }
  if (normalized == "coffee" || normalized == "cancoffee") {
    return task_presets::ManufacturingTarget::Coffee;
  }
  if (normalized == "coke" || normalized == "cola" || normalized == "cancoke") {
    return task_presets::ManufacturingTarget::Coke;
  }
  if (normalized == "hotdog" || normalized == "newyorkhotdog") {
    return task_presets::ManufacturingTarget::Hotdog;
  }
  if (normalized == "ketchup" || normalized == "kachup") {
    return task_presets::ManufacturingTarget::Ketchup;
  }
  if (normalized == "sausage") {
    return task_presets::ManufacturingTarget::Sausage;
  }
  throw std::invalid_argument("unsupported task '" + value + "'");
}

bool parseArmSide(const std::string & value, task_presets::ArmSide & arm)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized.empty() || normalized == "auto") {
    return false;
  }
  if (normalized == "left") {
    arm = task_presets::ArmSide::Left;
    return true;
  }
  if (normalized == "right") {
    arm = task_presets::ArmSide::Right;
    return true;
  }
  throw std::invalid_argument("unsupported arm '" + value + "'");
}

std::string selectTargetModelOverride(
  const std::string & requested_model,
  const std::string & default_model)
{
  return requested_model.empty() || requested_model == "auto" ? default_model : requested_model;
}

task_presets::ArmSide defaultArmForTarget(task_presets::ManufacturingTarget target)
{
  if (target == task_presets::ManufacturingTarget::Case) {
    return task_presets::ArmSide::Right;
  }
  return task_presets::ArmSide::Left;
}

bool isHotdogAssemblyEndpoint(task_presets::ManufacturingTarget target)
{
  return target == task_presets::ManufacturingTarget::Case ||
         target == task_presets::ManufacturingTarget::Bread ||
         target == task_presets::ManufacturingTarget::Sausage ||
         target == task_presets::ManufacturingTarget::Ketchup ||
         target == task_presets::ManufacturingTarget::Hotdog;
}

bool isBeverageTarget(task_presets::ManufacturingTarget target)
{
  return target == task_presets::ManufacturingTarget::Coke ||
         target == task_presets::ManufacturingTarget::Coffee;
}

double beveragePickupZoneYOffset(task_presets::ManufacturingTarget beverage_target)
{
  if (beverage_target == task_presets::ManufacturingTarget::Coffee) {
    return task_presets::kCoffeePickupZoneYOffsetM;
  }
  return task_presets::kCokePickupZoneYOffsetM;
}

std::string beverageTargetModel(
  task_presets::ManufacturingTarget beverage_target,
  const std::string & requested_model,
  const std::string & coffee_target_model,
  const std::string & coke_target_model)
{
  if (beverage_target == task_presets::ManufacturingTarget::Coffee) {
    return selectTargetModelOverride(requested_model, coffee_target_model);
  }
  return selectTargetModelOverride(requested_model, coke_target_model);
}

int hotdogAssemblyStepOrder(task_presets::ManufacturingTarget target)
{
  switch (target) {
    case task_presets::ManufacturingTarget::Case:
      return 1;
    case task_presets::ManufacturingTarget::Bread:
      return 2;
    case task_presets::ManufacturingTarget::Sausage:
      return 3;
    case task_presets::ManufacturingTarget::Ketchup:
      return 4;
    case task_presets::ManufacturingTarget::Hotdog:
      return 5;
    case task_presets::ManufacturingTarget::Coffee:
    case task_presets::ManufacturingTarget::Coke:
      return 0;
  }
  return 0;
}

bool stageEndpointFromWaypointName(
  const std::string & value,
  task_presets::ManufacturingStage & stage)
{
  const std::string normalized = normalizeStageName(value);
  if (normalized.empty() || normalized == "complete" || normalized == "all" ||
    normalized == "none")
  {
    return false;
  }
  if (normalized == "home") {
    stage = task_presets::ManufacturingStage::Home;
    return true;
  }
  if (normalized == "pick") {
    stage = task_presets::ManufacturingStage::Pick;
    return true;
  }
  if (normalized == "work") {
    stage = task_presets::ManufacturingStage::Work;
    return true;
  }
  if (normalized == "place") {
    stage = task_presets::ManufacturingStage::Place;
    return true;
  }
  if (normalized == "returnhome") {
    stage = task_presets::ManufacturingStage::ReturnHome;
    return true;
  }
  return false;
}

bool stageHintFromWaypointName(
  const std::string & value,
  task_presets::ManufacturingStage & stage)
{
  if (stageEndpointFromWaypointName(value, stage)) {
    return true;
  }

  const std::string normalized = normalizeStageName(value);
  if (normalized == "pregrasp" || normalized == "targetalign" || normalized == "clearance" ||
    normalized == "grasp" || normalized == "close" || normalized == "pullout" ||
    normalized == "lift")
  {
    stage = task_presets::ManufacturingStage::Pick;
    return true;
  }
  if (normalized == "casepresent" || normalized == "aim" || normalized == "squeezestart" ||
    normalized == "squeeze" || normalized == "handoff" || normalized == "prereceive" ||
    normalized == "receiveopen" || normalized == "receive" || normalized == "receiveclose" ||
    normalized == "leftpullout" || normalized == "leftretreat")
  {
    stage = task_presets::ManufacturingStage::Work;
    return true;
  }
  if (normalized == "move1" || normalized == "move2" || normalized == "approach" ||
    normalized == "returnpose" || normalized == "releasepose" || normalized == "release")
  {
    stage = task_presets::ManufacturingStage::Place;
    return true;
  }
  return false;
}

int stageOrder(task_presets::ManufacturingStage stage)
{
  switch (stage) {
    case task_presets::ManufacturingStage::Home:
      return 0;
    case task_presets::ManufacturingStage::Pick:
      return 1;
    case task_presets::ManufacturingStage::Work:
      return 2;
    case task_presets::ManufacturingStage::Place:
      return 3;
    case task_presets::ManufacturingStage::ReturnHome:
      return 4;
  }
  return 0;
}

bool shouldRunManufacturingStage(
  task_presets::ManufacturingStage stage,
  task_presets::ManufacturingStage start_stage)
{
  return stageOrder(stage) >= stageOrder(start_stage);
}

bool shouldStopAtOrBeforeStage(
  bool has_play_to_stage,
  task_presets::ManufacturingStage play_to_stage,
  task_presets::ManufacturingStage stage)
{
  return has_play_to_stage &&
         stageOrder(play_to_stage) <= stageOrder(stage);
}

bool shouldStopAtOrBeforeWaypointStage(
  const std::string & play_to_waypoint,
  task_presets::ManufacturingStage stage)
{
  if (play_to_waypoint.empty()) {
    return false;
  }

  task_presets::ManufacturingStage waypoint_stage = task_presets::ManufacturingStage::Home;
  if (stageHintFromWaypointName(play_to_waypoint, waypoint_stage)) {
    return stageOrder(waypoint_stage) <= stageOrder(stage);
  }

  for (const auto candidate_stage : {
      task_presets::ManufacturingStage::Home,
      task_presets::ManufacturingStage::Pick,
      task_presets::ManufacturingStage::Work,
      task_presets::ManufacturingStage::Place,
      task_presets::ManufacturingStage::ReturnHome})
  {
    const std::string prefix = normalizeStageName(task_presets::stageName(candidate_stage));
    if (play_to_waypoint.rfind(prefix, 0) == 0) {
      return stageOrder(candidate_stage) <= stageOrder(stage);
    }
  }

  return false;
}

bool stopWaypointMatches(
  const std::string & play_to_waypoint,
  task_presets::ManufacturingStage stage,
  const std::string & waypoint)
{
  if (play_to_waypoint.empty()) {
    return false;
  }

  const std::string normalized_waypoint = normalizeStageName(waypoint);
  const std::string normalized_stage_waypoint =
    normalizeStageName(std::string(task_presets::stageName(stage)) + waypoint);
  return play_to_waypoint == normalized_waypoint ||
         play_to_waypoint == normalized_stage_waypoint;
}

std::vector<ScenarioStep> makeHotdogScenarioSteps()
{
  return {
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
}

}  // namespace ddooby_controller::manufacturing_task
