#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <builtin_interfaces/msg/duration.hpp>
#include <control_msgs/action/follow_joint_trajectory.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>
#include <trajectory_msgs/msg/joint_trajectory_point.hpp>

namespace
{
using FollowJointTrajectory = control_msgs::action::FollowJointTrajectory;
using GoalHandle = rclcpp_action::ServerGoalHandle<FollowJointTrajectory>;

double durationToSec(const builtin_interfaces::msg::Duration & duration)
{
  return static_cast<double>(duration.sec) + static_cast<double>(duration.nanosec) * 1e-9;
}

trajectory_msgs::msg::JointTrajectoryPoint makePoint(
  const std::vector<double> & positions,
  double time_from_start_sec)
{
  trajectory_msgs::msg::JointTrajectoryPoint point;
  point.positions = positions;
  point.time_from_start.sec = static_cast<int32_t>(std::floor(time_from_start_sec));
  point.time_from_start.nanosec =
    static_cast<uint32_t>((time_from_start_sec - std::floor(time_from_start_sec)) * 1e9);
  return point;
}
}  // namespace

class ForwardJointTrajectoryBridge : public rclcpp::Node
{
public:
  ForwardJointTrajectoryBridge()
  : Node("forward_joint_trajectory_bridge")
  {
    controller_name_ = declare_parameter<std::string>("controller_name", "joint_trajectory_controller");
    command_topic_ = declare_parameter<std::string>("command_topic", "/forward_position_controller/commands");
    joint_states_topic_ = declare_parameter<std::string>("joint_states_topic", "/joint_states");
    joint_names_ = declare_parameter<std::vector<std::string>>("joint_names", std::vector<std::string>{});
    publish_rate_hz_ = declare_parameter<double>("publish_rate_hz", 100.0);
    state_wait_timeout_sec_ = declare_parameter<double>("state_wait_timeout_sec", 5.0);
    hold_after_goal_sec_ = declare_parameter<double>("hold_after_goal_sec", 0.2);
    hold_when_idle_ = declare_parameter<bool>("hold_when_idle", true);
    idle_hold_publish_rate_hz_ = declare_parameter<double>("idle_hold_publish_rate_hz", 50.0);
    pre_hold_before_trajectory_sec_ = declare_parameter<double>("pre_hold_before_trajectory_sec", 0.15);
    skip_zero_time_start_point_ = declare_parameter<bool>("skip_zero_time_start_point", true);
    start_point_jump_warn_rad_ = declare_parameter<double>("start_point_jump_warn_rad", 0.05);
    goal_tolerance_rad_ = declare_parameter<double>("goal_tolerance_rad", 0.12);
    goal_settle_timeout_sec_ = declare_parameter<double>("goal_settle_timeout_sec", 3.0);
    goal_settle_required_sec_ = declare_parameter<double>("goal_settle_required_sec", 0.2);

    if (joint_names_.empty()) {
      throw std::runtime_error("joint_names parameter must not be empty");
    }

    command_pub_ = create_publisher<std_msgs::msg::Float64MultiArray>(command_topic_, 10);
    joint_state_sub_ = create_subscription<sensor_msgs::msg::JointState>(
      joint_states_topic_, rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::JointState::SharedPtr msg) { onJointState(std::move(msg)); });

    if (hold_when_idle_) {
      const auto period = std::chrono::duration<double>(
        1.0 / std::max(1.0, idle_hold_publish_rate_hz_));
      idle_hold_timer_ = create_wall_timer(
        std::chrono::duration_cast<std::chrono::nanoseconds>(period),
        [this]() { publishIdleHold(); });
    }

    const std::string action_name = "/" + controller_name_ + "/follow_joint_trajectory";
    action_server_ = rclcpp_action::create_server<FollowJointTrajectory>(
      this,
      action_name,
      std::bind(&ForwardJointTrajectoryBridge::handleGoal, this, std::placeholders::_1, std::placeholders::_2),
      std::bind(&ForwardJointTrajectoryBridge::handleCancel, this, std::placeholders::_1),
      std::bind(&ForwardJointTrajectoryBridge::handleAccepted, this, std::placeholders::_1));

    RCLCPP_INFO(
      get_logger(),
      "Forward trajectory bridge ready: action=%s, command_topic=%s, joints=%zu, rate=%.1f, goal_tol=%.3f",
      action_name.c_str(), command_topic_.c_str(), joint_names_.size(), publish_rate_hz_,
      goal_tolerance_rad_);
  }

private:
  rclcpp_action::GoalResponse handleGoal(
    const rclcpp_action::GoalUUID &,
    std::shared_ptr<const FollowJointTrajectory::Goal> goal)
  {
    bool expected = false;
    if (!executing_.compare_exchange_strong(expected, true)) {
      RCLCPP_WARN(get_logger(), "Rejecting trajectory goal because another goal is active");
      return rclcpp_action::GoalResponse::REJECT;
    }

    std::string error;
    if (!validateGoal(*goal, error)) {
      executing_.store(false);
      RCLCPP_ERROR(get_logger(), "Rejecting invalid trajectory goal: %s", error.c_str());
      return rclcpp_action::GoalResponse::REJECT;
    }

    return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
  }

  rclcpp_action::CancelResponse handleCancel(const std::shared_ptr<GoalHandle>)
  {
    return rclcpp_action::CancelResponse::ACCEPT;
  }

  void handleAccepted(const std::shared_ptr<GoalHandle> goal_handle)
  {
    std::thread([this, goal_handle]() { execute(goal_handle); }).detach();
  }

  void onJointState(sensor_msgs::msg::JointState::SharedPtr msg)
  {
    std::lock_guard<std::mutex> lock(state_mutex_);
    for (std::size_t i = 0; i < msg->name.size() && i < msg->position.size(); ++i) {
      latest_positions_[msg->name[i]] = msg->position[i];
    }
    received_state_ = true;
  }

  bool validateGoal(const FollowJointTrajectory::Goal & goal, std::string & error) const
  {
    if (goal.trajectory.points.empty()) {
      error = "trajectory has no points";
      return false;
    }

    for (const auto & joint_name : joint_names_) {
      if (std::find(goal.trajectory.joint_names.begin(), goal.trajectory.joint_names.end(), joint_name) ==
        goal.trajectory.joint_names.end())
      {
        error = "missing joint " + joint_name;
        return false;
      }
    }

    double previous_time = -1.0;
    for (const auto & point : goal.trajectory.points) {
      if (point.positions.size() != goal.trajectory.joint_names.size()) {
        error = "point positions size does not match trajectory joint_names";
        return false;
      }
      const double time = durationToSec(point.time_from_start);
      if (time < previous_time) {
        error = "point time_from_start is not monotonic";
        return false;
      }
      previous_time = time;
    }

    return true;
  }

  bool getCurrentPositions(std::vector<double> & positions)
  {
    const auto start = std::chrono::steady_clock::now();
    const auto timeout = std::chrono::duration<double>(state_wait_timeout_sec_);

    while (rclcpp::ok()) {
      {
        std::lock_guard<std::mutex> lock(state_mutex_);
        if (received_state_) {
          positions.clear();
          positions.reserve(joint_names_.size());
          bool all_found = true;
          for (const auto & joint_name : joint_names_) {
            const auto it = latest_positions_.find(joint_name);
            if (it == latest_positions_.end()) {
              all_found = false;
              break;
            }
            positions.push_back(it->second);
          }
          if (all_found) {
            return true;
          }
        }
      }

      if (std::chrono::steady_clock::now() - start > timeout) {
        return false;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    return false;
  }

  bool copyCurrentPositions(std::vector<double> & positions)
  {
    std::lock_guard<std::mutex> lock(state_mutex_);
    if (!received_state_) {
      return false;
    }

    positions.clear();
    positions.reserve(joint_names_.size());
    for (const auto & joint_name : joint_names_) {
      const auto it = latest_positions_.find(joint_name);
      if (it == latest_positions_.end()) {
        return false;
      }
      positions.push_back(it->second);
    }
    return true;
  }

  std::vector<double> reorderPoint(
    const trajectory_msgs::msg::JointTrajectoryPoint & point,
    const std::vector<std::size_t> & goal_indices) const
  {
    std::vector<double> reordered;
    reordered.reserve(goal_indices.size());
    for (const auto index : goal_indices) {
      reordered.push_back(point.positions[index]);
    }
    return reordered;
  }

  std::vector<double> interpolate(
    const std::vector<double> & from,
    const std::vector<double> & to,
    double ratio) const
  {
    ratio = std::max(0.0, std::min(ratio, 1.0));
    std::vector<double> output;
    output.reserve(from.size());
    for (std::size_t i = 0; i < from.size(); ++i) {
      output.push_back(from[i] + (to[i] - from[i]) * ratio);
    }
    return output;
  }

  void publishCommand(const std::vector<double> & command)
  {
    {
      std::lock_guard<std::mutex> lock(command_mutex_);
      last_command_ = command;
      have_last_command_ = true;
    }

    std_msgs::msg::Float64MultiArray msg;
    msg.data = command;
    command_pub_->publish(msg);
  }

  void publishIdleHold()
  {
    if (executing_.load()) {
      return;
    }

    std::vector<double> command;
    {
      std::lock_guard<std::mutex> lock(command_mutex_);
      if (have_last_command_) {
        command = last_command_;
      }
    }

    if (command.empty() && !copyCurrentPositions(command)) {
      return;
    }

    publishCommand(command);
  }

  void publishFeedback(
    const std::shared_ptr<GoalHandle> & goal_handle,
    const std::vector<double> & desired,
    double elapsed_sec)
  {
    auto feedback = std::make_shared<FollowJointTrajectory::Feedback>();
    feedback->header.stamp = now();
    feedback->joint_names = joint_names_;
    feedback->desired = makePoint(desired, elapsed_sec);

    std::vector<double> actual;
    if (copyCurrentPositions(actual)) {
      feedback->actual = makePoint(actual, elapsed_sec);
      std::vector<double> error;
      error.reserve(desired.size());
      for (std::size_t i = 0; i < desired.size(); ++i) {
        error.push_back(desired[i] - actual[i]);
      }
      feedback->error = makePoint(error, elapsed_sec);
    }

    goal_handle->publish_feedback(feedback);
  }

  double maxPositionError(const std::vector<double> & desired)
  {
    std::vector<double> actual;
    if (!copyCurrentPositions(actual) || actual.size() != desired.size()) {
      return std::numeric_limits<double>::infinity();
    }

    double max_error = 0.0;
    for (std::size_t i = 0; i < desired.size(); ++i) {
      max_error = std::max(max_error, std::abs(desired[i] - actual[i]));
    }
    return max_error;
  }

  double maxAbsDiff(const std::vector<double> & lhs, const std::vector<double> & rhs) const
  {
    if (lhs.size() != rhs.size()) {
      return std::numeric_limits<double>::infinity();
    }

    double max_diff = 0.0;
    for (std::size_t i = 0; i < lhs.size(); ++i) {
      max_diff = std::max(max_diff, std::abs(lhs[i] - rhs[i]));
    }
    return max_diff;
  }

  bool waitForGoalSettled(
    const std::shared_ptr<GoalHandle> & goal_handle,
    const std::vector<double> & goal_positions,
    rclcpp::Rate & rate)
  {
    if (goal_settle_timeout_sec_ <= 0.0 || goal_tolerance_rad_ <= 0.0) {
      return true;
    }

    const auto start = std::chrono::steady_clock::now();
    const auto timeout = std::chrono::duration<double>(goal_settle_timeout_sec_);
    const auto required = std::chrono::duration<double>(goal_settle_required_sec_);
    bool has_within_since = false;
    std::chrono::steady_clock::time_point within_since;
    double last_error = std::numeric_limits<double>::infinity();

    while (rclcpp::ok()) {
      if (goal_handle->is_canceling()) {
        return false;
      }

      const auto now_time = std::chrono::steady_clock::now();
      last_error = maxPositionError(goal_positions);
      if (last_error <= goal_tolerance_rad_) {
        if (!has_within_since) {
          within_since = now_time;
          has_within_since = true;
        }
        if (now_time - within_since >= required) {
          return true;
        }
      } else {
        has_within_since = false;
      }

      if (now_time - start >= timeout) {
        RCLCPP_WARN(
          get_logger(),
          "Goal did not settle within %.2fs: max joint error %.4f rad exceeds tolerance %.4f rad",
          goal_settle_timeout_sec_, last_error, goal_tolerance_rad_);
        return false;
      }

      publishCommand(goal_positions);
      publishFeedback(
        goal_handle,
        goal_positions,
        std::chrono::duration<double>(now_time - start).count());
      rate.sleep();
    }

    return false;
  }

  void execute(const std::shared_ptr<GoalHandle> goal_handle)
  {
    auto clear_execution = [this]() { executing_.store(false); };

    const auto goal = goal_handle->get_goal();
    std::vector<std::size_t> goal_indices;
    goal_indices.reserve(joint_names_.size());
    for (const auto & joint_name : joint_names_) {
      const auto it =
        std::find(goal->trajectory.joint_names.begin(), goal->trajectory.joint_names.end(), joint_name);
      goal_indices.push_back(static_cast<std::size_t>(std::distance(goal->trajectory.joint_names.begin(), it)));
    }

    std::vector<double> start_positions;
    if (!getCurrentPositions(start_positions)) {
      auto result = std::make_shared<FollowJointTrajectory::Result>();
      result->error_code = FollowJointTrajectory::Result::INVALID_GOAL;
      result->error_string = "No complete joint state received before executing trajectory";
      RCLCPP_ERROR(
        get_logger(),
        "No complete joint state received within %.2fs; rejecting trajectory for safety",
        state_wait_timeout_sec_);
      goal_handle->abort(result);
      clear_execution();
      return;
    }

    std::vector<double> previous_positions = start_positions;
    double previous_time = 0.0;
    rclcpp::Rate rate(std::max(1.0, publish_rate_hz_));

    publishCommand(start_positions);
    const auto pre_hold_until =
      std::chrono::steady_clock::now() +
      std::chrono::milliseconds(static_cast<int64_t>(pre_hold_before_trajectory_sec_ * 1000.0));
    while (rclcpp::ok() && std::chrono::steady_clock::now() < pre_hold_until) {
      if (goal_handle->is_canceling()) {
        auto result = std::make_shared<FollowJointTrajectory::Result>();
        result->error_code = FollowJointTrajectory::Result::SUCCESSFUL;
        result->error_string = "Canceled before trajectory start";
        goal_handle->canceled(result);
        clear_execution();
        return;
      }
      publishCommand(start_positions);
      rate.sleep();
    }

    const auto start = std::chrono::steady_clock::now();

    bool first_point = true;
    for (const auto & point : goal->trajectory.points) {
      const auto target_positions = reorderPoint(point, goal_indices);
      const double target_time = durationToSec(point.time_from_start);
      const double segment_duration = std::max(0.0, target_time - previous_time);

      if (first_point && skip_zero_time_start_point_ && target_time <= 1e-6) {
        const double start_jump = maxAbsDiff(start_positions, target_positions);
        if (start_jump > start_point_jump_warn_rad_) {
          RCLCPP_WARN(
            get_logger(),
            "Skipping zero-time trajectory start point: max joint delta %.4f rad from current state",
            start_jump);
        }
        previous_positions = start_positions;
        previous_time = target_time;
        first_point = false;
        continue;
      }
      first_point = false;

      while (rclcpp::ok()) {
        if (goal_handle->is_canceling()) {
          auto result = std::make_shared<FollowJointTrajectory::Result>();
          result->error_code = FollowJointTrajectory::Result::SUCCESSFUL;
          result->error_string = "Canceled";
          goal_handle->canceled(result);
          clear_execution();
          return;
        }

        const double elapsed =
          std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        if (elapsed >= target_time) {
          break;
        }

        const double ratio =
          segment_duration > 1e-6 ? (elapsed - previous_time) / segment_duration : 1.0;
        const auto command = interpolate(previous_positions, target_positions, ratio);
        publishCommand(command);
        publishFeedback(goal_handle, command, elapsed);
        rate.sleep();
      }

      publishCommand(target_positions);
      publishFeedback(goal_handle, target_positions, target_time);
      previous_positions = target_positions;
      previous_time = target_time;
    }

    const auto hold_until =
      std::chrono::steady_clock::now() +
      std::chrono::milliseconds(static_cast<int64_t>(hold_after_goal_sec_ * 1000.0));
    while (rclcpp::ok() && std::chrono::steady_clock::now() < hold_until) {
      publishCommand(previous_positions);
      rate.sleep();
    }

    if (!waitForGoalSettled(goal_handle, previous_positions, rate)) {
      if (goal_handle->is_canceling()) {
        auto result = std::make_shared<FollowJointTrajectory::Result>();
        result->error_code = FollowJointTrajectory::Result::SUCCESSFUL;
        result->error_string = "Canceled while waiting for goal settle";
        goal_handle->canceled(result);
      } else {
        auto result = std::make_shared<FollowJointTrajectory::Result>();
        result->error_code = FollowJointTrajectory::Result::PATH_TOLERANCE_VIOLATED;
        result->error_string = "Goal did not settle before timeout";
        goal_handle->abort(result);
      }
      clear_execution();
      return;
    }

    auto result = std::make_shared<FollowJointTrajectory::Result>();
    result->error_code = FollowJointTrajectory::Result::SUCCESSFUL;
    result->error_string = "Forward position trajectory bridge completed";
    goal_handle->succeed(result);
    clear_execution();
  }

  std::string controller_name_;
  std::string command_topic_;
  std::string joint_states_topic_;
  std::vector<std::string> joint_names_;
  double publish_rate_hz_;
  double state_wait_timeout_sec_;
  double hold_after_goal_sec_;
  bool hold_when_idle_;
  double idle_hold_publish_rate_hz_;
  double pre_hold_before_trajectory_sec_;
  bool skip_zero_time_start_point_;
  double start_point_jump_warn_rad_;
  double goal_tolerance_rad_;
  double goal_settle_timeout_sec_;
  double goal_settle_required_sec_;

  std::mutex state_mutex_;
  bool received_state_{false};
  std::map<std::string, double> latest_positions_;
  std::atomic_bool executing_{false};

  std::mutex command_mutex_;
  bool have_last_command_{false};
  std::vector<double> last_command_;

  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr command_pub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_state_sub_;
  rclcpp::TimerBase::SharedPtr idle_hold_timer_;
  rclcpp_action::Server<FollowJointTrajectory>::SharedPtr action_server_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    rclcpp::spin(std::make_shared<ForwardJointTrajectoryBridge>());
  } catch (const std::exception & e) {
    RCLCPP_FATAL(rclcpp::get_logger("forward_joint_trajectory_bridge"), "%s", e.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
