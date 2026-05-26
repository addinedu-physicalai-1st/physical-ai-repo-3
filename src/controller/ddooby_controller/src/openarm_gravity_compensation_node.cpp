#include <algorithm>
#include <cmath>
#include <memory>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "kdl/chaindynparam.hpp"
#include "kdl/chain.hpp"
#include "kdl/jntarray.hpp"
#include "kdl/tree.hpp"
#include "kdl_parser/kdl_parser.hpp"
#include "rcl_interfaces/msg/set_parameters_result.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"
#include "std_msgs/msg/float64_multi_array.hpp"
#include "std_msgs/msg/string.hpp"

namespace {

constexpr std::size_t kArmDof = 7;

double clamp_abs(double value, double limit) {
  if (limit <= 0.0) {
    return value;
  }
  return std::clamp(value, -limit, limit);
}

class ArmGravityModel {
 public:
  ArmGravityModel(std::string name, std::string root_link, std::string tip_link)
      : name_(std::move(name)),
        root_link_(std::move(root_link)),
        tip_link_(std::move(tip_link)) {}

  bool init_from_robot_description(const std::string& robot_description) {
    KDL::Tree tree;
    if (!kdl_parser::treeFromString(robot_description, tree)) {
      RCLCPP_ERROR(rclcpp::get_logger("openarm_gravity_compensation"),
                   "%s: failed to parse robot_description", name_.c_str());
      return false;
    }

    KDL::Chain chain;
    if (!tree.getChain(root_link_, tip_link_, chain)) {
      RCLCPP_ERROR(rclcpp::get_logger("openarm_gravity_compensation"),
                   "%s: failed to build KDL chain root=%s tip=%s",
                   name_.c_str(), root_link_.c_str(), tip_link_.c_str());
      return false;
    }

    std::vector<std::string> joint_names;
    for (unsigned int i = 0; i < chain.getNrOfSegments(); ++i) {
      const auto& joint = chain.getSegment(i).getJoint();
      if (joint.getType() != KDL::Joint::None) {
        joint_names.push_back(joint.getName());
      }
    }

    if (joint_names.size() != kArmDof) {
      RCLCPP_ERROR(rclcpp::get_logger("openarm_gravity_compensation"),
                   "%s: expected %zu joints, got %zu for root=%s tip=%s",
                   name_.c_str(), kArmDof, joint_names.size(),
                   root_link_.c_str(), tip_link_.c_str());
      return false;
    }

    chain_ = chain;
    joint_names_ = std::move(joint_names);
    q_.resize(kArmDof);
    gravity_torque_.resize(kArmDof);
    solver_ = std::make_unique<KDL::ChainDynParam>(
        chain_, KDL::Vector(0.0, 0.0, -9.81));
    initialized_ = true;

    RCLCPP_INFO(rclcpp::get_logger("openarm_gravity_compensation"),
                "%s gravity chain ready: %s -> %s",
                name_.c_str(), root_link_.c_str(), tip_link_.c_str());
    return true;
  }

  bool initialized() const { return initialized_; }

  std::vector<double> compute(
      const std::unordered_map<std::string, double>& joint_positions,
      double torque_scale, double max_abs_torque) {
    std::vector<double> output(kArmDof, 0.0);
    if (!initialized_ || !solver_) {
      return output;
    }

    for (std::size_t i = 0; i < joint_names_.size(); ++i) {
      const auto it = joint_positions.find(joint_names_[i]);
      if (it == joint_positions.end() || !std::isfinite(it->second)) {
        return output;
      }
      q_(i) = it->second;
    }

    if (solver_->JntToGravity(q_, gravity_torque_) < 0) {
      return output;
    }

    for (std::size_t i = 0; i < kArmDof; ++i) {
      output[i] = clamp_abs(gravity_torque_(i) * torque_scale, max_abs_torque);
    }
    return output;
  }

 private:
  std::string name_;
  std::string root_link_;
  std::string tip_link_;
  KDL::Chain chain_;
  KDL::JntArray q_;
  KDL::JntArray gravity_torque_;
  std::vector<std::string> joint_names_;
  std::unique_ptr<KDL::ChainDynParam> solver_;
  bool initialized_{false};
};

}  // namespace

class OpenArmGravityCompensationNode : public rclcpp::Node {
 public:
  OpenArmGravityCompensationNode()
      : Node("openarm_gravity_compensation"),
        left_model_("left", declare_parameter<std::string>(
                                "left_root_link", "openarm_body_link0"),
                    declare_parameter<std::string>(
                        "left_tip_link", "openarm_left_hand")),
        right_model_("right", declare_parameter<std::string>(
                                  "right_root_link", "openarm_body_link0"),
                     declare_parameter<std::string>(
                         "right_tip_link", "openarm_right_hand")) {
    enabled_ = declare_parameter<bool>("enabled", true);
    start_delay_sec_ = declare_parameter<double>("start_delay_sec", 8.0);
    publish_rate_hz_ = declare_parameter<double>("publish_rate_hz", 50.0);
    torque_scale_ = declare_parameter<double>("torque_scale", 0.25);
    max_abs_torque_ = declare_parameter<double>("max_abs_torque", 3.0);

    const auto left_topic = declare_parameter<std::string>(
        "left_command_topic", "/left_forward_effort_controller/commands");
    const auto right_topic = declare_parameter<std::string>(
        "right_command_topic", "/right_forward_effort_controller/commands");
    const auto robot_description_topic = declare_parameter<std::string>(
        "robot_description_topic", "/openarm_robot_description");

    left_pub_ =
        create_publisher<std_msgs::msg::Float64MultiArray>(left_topic, 10);
    right_pub_ =
        create_publisher<std_msgs::msg::Float64MultiArray>(right_topic, 10);

    robot_description_sub_ = create_subscription<std_msgs::msg::String>(
        robot_description_topic, rclcpp::QoS(1).transient_local().reliable(),
        [this](const std_msgs::msg::String::SharedPtr msg) {
          if (models_ready_) {
            return;
          }
          const bool left_ready =
              left_model_.init_from_robot_description(msg->data);
          const bool right_ready =
              right_model_.init_from_robot_description(msg->data);
          models_ready_ = left_ready && right_ready;
        });

    joint_state_sub_ = create_subscription<sensor_msgs::msg::JointState>(
        "/joint_states", rclcpp::SensorDataQoS(),
        [this](const sensor_msgs::msg::JointState::SharedPtr msg) {
          for (std::size_t i = 0; i < msg->name.size() &&
                                  i < msg->position.size();
               ++i) {
            joint_positions_[msg->name[i]] = msg->position[i];
          }
          have_joint_state_ = true;
        });

    start_time_ = now();
    const double period_sec = 1.0 / std::max(1.0, publish_rate_hz_);
    timer_ = create_wall_timer(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::duration<double>(period_sec)),
        [this]() { publish_gravity_commands(); });

    parameter_callback_handle_ = add_on_set_parameters_callback(
        [this](const std::vector<rclcpp::Parameter>& parameters) {
          return on_parameters(parameters);
        });

    RCLCPP_INFO(get_logger(),
                "Gravity compensation node ready: enabled=%s, delay=%.2fs, scale=%.3f, max_abs_torque=%.3f",
                enabled_ ? "true" : "false", start_delay_sec_, torque_scale_,
                max_abs_torque_);
  }

 private:
  rcl_interfaces::msg::SetParametersResult on_parameters(
      const std::vector<rclcpp::Parameter>& parameters) {
    rcl_interfaces::msg::SetParametersResult result;
    result.successful = true;

    for (const auto& parameter : parameters) {
      if (parameter.get_name() == "enabled") {
        if (parameter.get_type() != rclcpp::ParameterType::PARAMETER_BOOL) {
          result.successful = false;
          result.reason = "enabled must be a bool";
          return result;
        }
        enabled_ = parameter.as_bool();
      } else if (parameter.get_name() == "torque_scale") {
        if (parameter.get_type() != rclcpp::ParameterType::PARAMETER_DOUBLE ||
            parameter.as_double() < -2.0 || parameter.as_double() > 2.0) {
          result.successful = false;
          result.reason = "torque_scale must be a double in [-2.0, 2.0]";
          return result;
        }
        torque_scale_ = parameter.as_double();
      } else if (parameter.get_name() == "max_abs_torque") {
        if (parameter.get_type() != rclcpp::ParameterType::PARAMETER_DOUBLE ||
            parameter.as_double() < 0.0 || parameter.as_double() > 10.0) {
          result.successful = false;
          result.reason = "max_abs_torque must be a double in [0.0, 10.0]";
          return result;
        }
        max_abs_torque_ = parameter.as_double();
      }
    }

    RCLCPP_INFO(get_logger(),
                "Gravity compensation updated: enabled=%s, scale=%.3f, max_abs_torque=%.3f",
                enabled_ ? "true" : "false", torque_scale_, max_abs_torque_);
    return result;
  }

  void publish_gravity_commands() {
    std::vector<double> left(kArmDof, 0.0);
    std::vector<double> right(kArmDof, 0.0);

    const bool delay_done = (now() - start_time_).seconds() >= start_delay_sec_;
    if (enabled_ && delay_done && models_ready_ && have_joint_state_) {
      left = left_model_.compute(joint_positions_, torque_scale_, max_abs_torque_);
      right = right_model_.compute(joint_positions_, torque_scale_, max_abs_torque_);
    }

    publish(left_pub_, left);
    publish(right_pub_, right);
  }

  static void publish(
      const rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr& pub,
      const std::vector<double>& values) {
    std_msgs::msg::Float64MultiArray msg;
    msg.data = values;
    pub->publish(msg);
  }

  bool enabled_{true};
  double start_delay_sec_{8.0};
  double publish_rate_hz_{50.0};
  double torque_scale_{0.25};
  double max_abs_torque_{3.0};
  bool models_ready_{false};
  bool have_joint_state_{false};
  rclcpp::Time start_time_;
  std::unordered_map<std::string, double> joint_positions_;
  ArmGravityModel left_model_;
  ArmGravityModel right_model_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr robot_description_sub_;
  rclcpp::Subscription<sensor_msgs::msg::JointState>::SharedPtr joint_state_sub_;
  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr left_pub_;
  rclcpp::Publisher<std_msgs::msg::Float64MultiArray>::SharedPtr right_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr
      parameter_callback_handle_;
};

int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<OpenArmGravityCompensationNode>());
  rclcpp::shutdown();
  return 0;
}
