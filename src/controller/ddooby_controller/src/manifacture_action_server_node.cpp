#include <chrono>
#include <cerrno>
#include <csignal>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include <custom_msg/action/manifacture.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

namespace
{
using namespace std::chrono_literals;

using Manifacture = custom_msg::action::Manifacture;
using GoalHandleManifacture = rclcpp_action::ServerGoalHandle<Manifacture>;

struct BeverageRun
{
  std::string item_name;
  std::string ingredient_model;
  int item_run_index;
  int item_run_count;
};

struct ProcessResult
{
  bool success;
  bool canceled;
  std::string message;
};

struct CommandResult
{
  bool success;
  bool canceled;
  int exit_code;
  std::string output;
  std::string message;
};

struct GazeboResetPose
{
  std::string name;
  double x;
  double y;
  double z;
};

std::string toLowerAscii(const std::string & value)
{
  std::string lowered;
  lowered.reserve(value.size());
  for (const unsigned char ch : value) {
    lowered.push_back(static_cast<char>(std::tolower(ch)));
  }
  return lowered;
}

bool containsAny(const std::string & value, const std::vector<std::string> & needles)
{
  for (const auto & needle : needles) {
    if (value.find(needle) != std::string::npos) {
      return true;
    }
  }
  return false;
}

std::optional<std::string> manufactureBackendForItem(const std::string & item_name)
{
  const std::string lowered = toLowerAscii(item_name);
  if (lowered == "hotdog" || lowered == "hot dog" ||
    containsAny(lowered, {"new york", "핫도그", "뉴욕"}))
  {
    return "hotdog_placeholder";
  }
  if (lowered == "coke" || lowered == "cola" || containsAny(lowered, {"콜라"})) {
    return "ade_cup";
  }
  if (lowered == "coffee" || containsAny(lowered, {"커피"})) {
    return "espresso_cup";
  }
  return std::nullopt;
}

bool isHotdogPlaceholder(const BeverageRun & run)
{
  return run.ingredient_model == "hotdog_placeholder";
}

std::string joinCommandForLog(const std::vector<std::string> & args)
{
  std::ostringstream stream;
  for (size_t i = 0; i < args.size(); ++i) {
    if (i > 0) {
      stream << ' ';
    }
    stream << args[i];
  }
  return stream.str();
}


void trimProcessOutputTail(std::string & output)
{
  constexpr size_t kMaxProcessOutputTail = 8192;
  if (output.size() > kMaxProcessOutputTail) {
    output.erase(0, output.size() - kMaxProcessOutputTail);
  }
}

bool containsBeverageSuccessMarker(const std::string & output)
{
  return output.find("Beverage task manager sequence completed") != std::string::npos;
}

bool containsBeverageFailureMarker(const std::string & output)
{
  return output.find("process has died") != std::string::npos ||
         output.find("failed to exec") != std::string::npos ||
         output.find("Gazebo set pose service") != std::string::npos ||
         output.find("Timed out resetting Gazebo model") != std::string::npos ||
         output.find("Gazebo rejected reset pose") != std::string::npos ||
         output.find("RuntimeError:") != std::string::npos ||
         output.find("Traceback (most recent call last)") != std::string::npos;
}

void readAvailableProcessOutput(
  int output_fd,
  std::string & output_tail,
  bool & saw_success_marker,
  bool & saw_failure_marker)
{
  char buffer[4096];
  while (true) {
    const ssize_t bytes_read = read(output_fd, buffer, sizeof(buffer));
    if (bytes_read > 0) {
      std::fwrite(buffer, 1, static_cast<size_t>(bytes_read), stdout);
      std::fflush(stdout);

      output_tail.append(buffer, static_cast<size_t>(bytes_read));
      trimProcessOutputTail(output_tail);
      saw_success_marker = saw_success_marker || containsBeverageSuccessMarker(output_tail);
      saw_failure_marker = saw_failure_marker || containsBeverageFailureMarker(output_tail);
      continue;
    }
    if (bytes_read == 0) {
      return;
    }
    if (errno == EINTR) {
      continue;
    }
    if (errno == EAGAIN || errno == EWOULDBLOCK) {
      return;
    }
    return;
  }
}

class ManifactureActionServer : public rclcpp::Node
{
public:
  ManifactureActionServer()
  : Node("ddooby_manifacture_action_server")
  {
    action_name_ = declare_parameter<std::string>("action_name", "ddooby/manifacture");
    ros2_executable_ = declare_parameter<std::string>("ros2_executable", "ros2");
    gz_executable_ = declare_parameter<std::string>("gz_executable", "gz");
    beverage_launch_package_ =
      declare_parameter<std::string>("beverage_launch_package", "ddooby_controller");
    beverage_launch_file_ =
      declare_parameter<std::string>("beverage_launch_file", "beverage_making_test.launch.py");
    hotdog_launch_package_ =
      declare_parameter<std::string>("hotdog_launch_package", "ddooby_controller");
    hotdog_launch_file_ =
      declare_parameter<std::string>("hotdog_launch_file", "hotdog_making.launch.py");
    hotdog_use_sim_time_ = declare_parameter<bool>("hotdog_use_sim_time", true);
    reset_world_on_start_ = declare_parameter<bool>("reset_world_on_start", true);
    use_gz_cli_reset_ = declare_parameter<bool>("use_gz_cli_reset", true);
    gazebo_set_pose_service_ =
      declare_parameter<std::string>("gazebo_set_pose_service", "/world/default/set_pose");
    gazebo_reset_timeout_ms_ = declare_parameter<int>("gazebo_reset_timeout_ms", 3000);
    gazebo_reset_settle_sec_ = declare_parameter<double>("gazebo_reset_settle_sec", 1.0);
    start_step_ = declare_parameter<std::string>("start_step", "");
    end_step_ = declare_parameter<std::string>("end_step", "");
    command_timeout_sec_ = declare_parameter<double>("command_timeout_sec", 0.0);
    execution_backend_ =
      declare_parameter<std::string>("execution_backend", "temporary_beverage_test");
    hotdog_task_executable_ =
      declare_parameter<std::string>("hotdog_task_executable", "hotdog_making_node");
    drink_task_executable_ =
      declare_parameter<std::string>("drink_task_executable", "drink_serving_node");
    scenario_step_delay_ms_ = declare_parameter<int>("scenario_step_delay_ms", 150);

    if (execution_backend_ != "temporary_beverage_test" &&
        execution_backend_ != "scenario_task_nodes")
    {
      RCLCPP_WARN(
        get_logger(),
        "Unknown execution_backend '%s'; falling back to temporary_beverage_test",
        execution_backend_.c_str());
      execution_backend_ = "temporary_beverage_test";
    }

    using std::placeholders::_1;
    using std::placeholders::_2;
    action_server_ = rclcpp_action::create_server<Manifacture>(
      this,
      action_name_,
      std::bind(&ManifactureActionServer::handleGoal, this, _1, _2),
      std::bind(&ManifactureActionServer::handleCancel, this, _1),
      std::bind(&ManifactureActionServer::handleAccepted, this, _1));

    RCLCPP_INFO(get_logger(), "DDooby manufacture action server ready: %s", action_name_.c_str());
  }

private:
  class ActiveGoalGuard
  {
  public:
    explicit ActiveGoalGuard(ManifactureActionServer & server)
    : server_(server)
    {
    }

    ~ActiveGoalGuard()
    {
      std::lock_guard<std::mutex> lock(server_.active_goal_mutex_);
      server_.active_goal_ = false;
    }

  private:
    ManifactureActionServer & server_;
  };

  rclcpp_action::GoalResponse handleGoal(
    const rclcpp_action::GoalUUID &,
    std::shared_ptr<const Manifacture::Goal> goal)
  {
    std::lock_guard<std::mutex> lock(active_goal_mutex_);
    if (active_goal_) {
      RCLCPP_WARN(get_logger(), "Rejecting manufacture goal because another goal is active");
      return rclcpp_action::GoalResponse::REJECT;
    }
    active_goal_ = true;

    RCLCPP_INFO(get_logger(), "Accepted manufacture goal with %zu item entries", goal->items.size());
    return rclcpp_action::GoalResponse::ACCEPT_AND_EXECUTE;
  }

  rclcpp_action::CancelResponse handleCancel(
    const std::shared_ptr<GoalHandleManifacture>)
  {
    RCLCPP_INFO(get_logger(), "Cancel requested for active manufacture goal");
    return rclcpp_action::CancelResponse::ACCEPT;
  }

  void handleAccepted(const std::shared_ptr<GoalHandleManifacture> goal_handle)
  {
    std::thread{std::bind(&ManifactureActionServer::executeGoal, this, goal_handle)}.detach();
  }

  void executeGoal(const std::shared_ptr<GoalHandleManifacture> goal_handle)
  {
    ActiveGoalGuard guard(*this);

    std::vector<BeverageRun> run_plan;
    std::string plan_error;
    if (!buildRunPlan(goal_handle->get_goal(), run_plan, plan_error)) {
      finishAborted(goal_handle, plan_error);
      return;
    }

    publishStatus(
      goal_handle,
      "manufacture started: " + std::to_string(run_plan.size()) + " task(s)");

    for (size_t index = 0; index < run_plan.size(); ++index) {
      if (goal_handle->is_canceling()) {
        finishCanceled(goal_handle, "manufacture canceled before next beverage test run");
        return;
      }

      const auto & run = run_plan[index];
      std::ostringstream status;
      status << "manufacturing " << run.item_name << " with ";
      if (isHotdogPlaceholder(run)) {
        status << hotdog_task_executable_;
      } else if (useScenarioTaskNodes()) {
        status << drink_task_executable_;
      } else {
        status << run.ingredient_model;
      }
      status << " (run " << (index + 1) << "/" << run_plan.size() << ", item "
             << run.item_run_index << "/" << run.item_run_count << ")";
      publishStatus(goal_handle, status.str());

      const ProcessResult process_result = runManufactureTask(goal_handle, run);
      if (process_result.canceled) {
        finishCanceled(goal_handle, process_result.message);
        return;
      }
      if (!process_result.success) {
        finishAborted(goal_handle, process_result.message);
        return;
      }

      publishStatus(
        goal_handle,
        "completed " + run.item_name + " run " + std::to_string(run.item_run_index) + "/" +
          std::to_string(run.item_run_count));
    }

    auto result = std::make_shared<Manifacture::Result>();
    result->success = true;
    result->message =
      "manufacture completed: " + std::to_string(run_plan.size()) + " task(s)";
    goal_handle->succeed(result);
    RCLCPP_INFO(get_logger(), "%s", result->message.c_str());
  }

  bool buildRunPlan(
    const std::shared_ptr<const Manifacture::Goal> & goal,
    std::vector<BeverageRun> & run_plan,
    std::string & error) const
  {
    if (goal->items.empty()) {
      error = "manufacture goal has no items";
      return false;
    }

    for (const auto & item : goal->items) {
      if (item.count < 0) {
        error = "manufacture item '" + item.name + "' has negative count";
        return false;
      }
      if (item.count == 0) {
        continue;
      }

      const auto ingredient_model = manufactureBackendForItem(item.name);
      if (!ingredient_model.has_value()) {
        error =
          "unsupported manufacture item '" + item.name +
          "': backend supports hotdog, coke, and coffee items only";
        return false;
      }

      for (int run_index = 1; run_index <= item.count; ++run_index) {
        run_plan.push_back(BeverageRun{
          item.name,
          ingredient_model.value(),
          run_index,
          item.count,
        });
      }
    }

    if (run_plan.empty()) {
      error = "manufacture goal has no positive item counts";
      return false;
    }
    return true;
  }

  std::string makeGzSetPoseRequest(const GazeboResetPose & pose) const
  {
    std::ostringstream request;
    request << "name: \"" << pose.name << "\" "
            << "position { x: " << pose.x << " y: " << pose.y << " z: " << pose.z << " } "
            << "orientation { w: 1.0 }";
    return request.str();
  }

  CommandResult runCommandAndCollectOutput(
    const std::vector<std::string> & args,
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    double timeout_sec) const
  {
    int output_pipe[2];
    if (pipe(output_pipe) != 0) {
      return CommandResult{false, false, -1, "", "failed to create process output pipe"};
    }

    const int flags = fcntl(output_pipe[0], F_GETFL, 0);
    if (flags >= 0) {
      fcntl(output_pipe[0], F_SETFL, flags | O_NONBLOCK);
    }

    const pid_t pid = fork();
    if (pid < 0) {
      close(output_pipe[0]);
      close(output_pipe[1]);
      return CommandResult{false, false, -1, "", "failed to fork process"};
    }

    if (pid == 0) {
      setpgid(0, 0);
      close(output_pipe[0]);
      dup2(output_pipe[1], STDOUT_FILENO);
      dup2(output_pipe[1], STDERR_FILENO);
      if (output_pipe[1] > STDERR_FILENO) {
        close(output_pipe[1]);
      }

      std::vector<char *> argv;
      argv.reserve(args.size() + 1);
      for (const auto & arg : args) {
        argv.push_back(const_cast<char *>(arg.c_str()));
      }
      argv.push_back(nullptr);
      execvp(argv[0], argv.data());
      std::fprintf(stderr, "failed to exec %s: %s\n", argv[0], std::strerror(errno));
      _exit(127);
    }

    close(output_pipe[1]);
    auto finish = [&](CommandResult result) {
      close(output_pipe[0]);
      return result;
    };

    setpgid(pid, pid);
    std::string output_tail;
    bool ignored_success_marker = false;
    bool ignored_failure_marker = false;
    const auto start_time = std::chrono::steady_clock::now();
    while (rclcpp::ok()) {
      readAvailableProcessOutput(
        output_pipe[0], output_tail, ignored_success_marker, ignored_failure_marker);

      int status = 0;
      const pid_t wait_result = waitpid(pid, &status, WNOHANG);
      if (wait_result == pid) {
        readAvailableProcessOutput(
          output_pipe[0], output_tail, ignored_success_marker, ignored_failure_marker);
        if (WIFEXITED(status)) {
          const int exit_code = WEXITSTATUS(status);
          return finish(CommandResult{
            exit_code == 0,
            false,
            exit_code,
            output_tail,
            "process exited with code " + std::to_string(exit_code)});
        }
        if (WIFSIGNALED(status)) {
          return finish(CommandResult{
            false,
            false,
            -1,
            output_tail,
            "process terminated by signal " + std::to_string(WTERMSIG(status))});
        }
        return finish(CommandResult{false, false, -1, output_tail, "process failed"});
      }
      if (wait_result < 0 && errno != EINTR) {
        return finish(CommandResult{false, false, -1, output_tail, "failed while waiting for process"});
      }

      if (goal_handle->is_canceling()) {
        terminateProcessGroup(pid);
        return finish(CommandResult{false, true, -1, output_tail, "process canceled"});
      }

      if (timeout_sec > 0.0) {
        const auto elapsed =
          std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time).count();
        if (elapsed > timeout_sec) {
          terminateProcessGroup(pid);
          return finish(CommandResult{false, false, -1, output_tail, "process timed out"});
        }
      }

      std::this_thread::sleep_for(100ms);
    }

    terminateProcessGroup(pid);
    return finish(CommandResult{false, true, -1, output_tail, "ROS shutdown requested"});
  }

  ProcessResult resetGazeboObjectsWithGzCli(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle) const
  {
    const std::vector<GazeboResetPose> poses{
      {"espresso_cup", 0.38, 0.21, 0.425},
      {"ade_cup", 0.38, 0.07, 0.425},
      {"mixing_cup", 0.38, -0.08, 0.425},
      {"water_cup", 0.38, -0.22, 0.425},
      {"stir_stick_holder", 0.38, 0.36, 0.37},
      {"stir_stick", 0.38, 0.36, 0.48},
      {"pickup_zone", 0.025, -0.50, 0.35},
    };

    const double timeout_sec = static_cast<double>(gazebo_reset_timeout_ms_) / 1000.0 + 1.0;
    for (const auto & pose : poses) {
      std::vector<std::string> args{
        gz_executable_,
        "service",
        "-s",
        gazebo_set_pose_service_,
        "--reqtype",
        "gz.msgs.Pose",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        std::to_string(gazebo_reset_timeout_ms_),
        "--req",
        makeGzSetPoseRequest(pose),
      };
      RCLCPP_INFO(get_logger(), "Resetting Gazebo model with CLI: %s", pose.name.c_str());
      const auto command_result = runCommandAndCollectOutput(args, goal_handle, timeout_sec);
      if (command_result.canceled) {
        return ProcessResult{false, true, "manufacture canceled while resetting Gazebo objects"};
      }
      if (!command_result.success || command_result.output.find("data: true") == std::string::npos) {
        return ProcessResult{
          false,
          false,
          "failed to reset Gazebo model '" + pose.name + "' through gz service: " +
            command_result.message};
      }
    }

    if (gazebo_reset_settle_sec_ > 0.0) {
      std::this_thread::sleep_for(std::chrono::duration<double>(gazebo_reset_settle_sec_));
    }
    return ProcessResult{true, false, "Gazebo beverage objects reset"};
  }

  bool useScenarioTaskNodes() const
  {
    return execution_backend_ == "scenario_task_nodes";
  }

  ProcessResult runManufactureTask(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const BeverageRun & run) const
  {
    if (isHotdogPlaceholder(run)) {
      return runHotdogTaskLaunch(goal_handle, run);
    }

    if (useScenarioTaskNodes()) {
      return runScenarioTaskProcess(
        goal_handle,
        run,
        drink_task_executable_,
        "Drink serving scenario completed",
        run.ingredient_model);
    }

    return runBeverageTestProcess(goal_handle, run);
  }

  ProcessResult runHotdogTaskLaunch(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const BeverageRun & run) const
  {
    std::vector<std::string> args{
      ros2_executable_,
      "launch",
      "--noninteractive",
      "--show-all-subprocesses-output",
      hotdog_launch_package_,
      hotdog_launch_file_,
      "task:=hotdog",
      std::string("use_sim_time:=") + (hotdog_use_sim_time_ ? "true" : "false"),
    };

    RCLCPP_INFO(get_logger(), "Starting hotdog manufacture process: %s", joinCommandForLog(args).c_str());
    const auto command_result = runCommandAndCollectOutput(args, goal_handle, command_timeout_sec_);
    if (command_result.canceled) {
      return ProcessResult{false, true, "manufacture canceled while running hotdog task"};
    }
    if (!command_result.success) {
      return ProcessResult{
        false,
        false,
        "hotdog manufacture failed for item '" + run.item_name + "': " + command_result.message};
    }
    if (command_result.output.find("New York hotdog assembly completed") == std::string::npos) {
      return ProcessResult{
        false,
        false,
        "hotdog manufacture exited without completion marker for item '" + run.item_name + "'"};
    }

    return ProcessResult{true, false, "hotdog manufacture completed"};
  }

  ProcessResult runScenarioTaskProcess(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const BeverageRun & run,
    const std::string & executable,
    const std::string & success_marker,
    const std::string & drink_model) const
  {
    std::vector<std::string> args{
      ros2_executable_,
      "run",
      "ddooby_controller",
      executable,
      "--ros-args",
      "-p",
      "item_name:=" + run.item_name,
      "-p",
      "scenario_only:=true",
      "-p",
      "step_delay_ms:=" + std::to_string(scenario_step_delay_ms_),
    };
    if (!drink_model.empty()) {
      args.push_back("-p");
      args.push_back("drink_model:=" + drink_model);
    }

    RCLCPP_INFO(get_logger(), "Starting scenario task process: %s", joinCommandForLog(args).c_str());
    const auto command_result = runCommandAndCollectOutput(args, goal_handle, command_timeout_sec_);
    if (command_result.canceled) {
      return ProcessResult{false, true, "manufacture canceled while running " + executable};
    }
    if (!command_result.success) {
      return ProcessResult{
        false,
        false,
        executable + " failed for item '" + run.item_name + "': " + command_result.message};
    }
    if (command_result.output.find(success_marker) == std::string::npos) {
      return ProcessResult{
        false,
        false,
        executable + " exited without success marker for item '" + run.item_name + "'"};
    }

    return ProcessResult{true, false, executable + " completed"};
  }

  ProcessResult runBeverageTestProcess(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const BeverageRun & run) const
  {
    if (isHotdogPlaceholder(run)) {
      return runScenarioTaskProcess(
        goal_handle,
        run,
        hotdog_task_executable_,
        "Hotdog task scenario completed",
        "");
    }

    if (reset_world_on_start_ && use_gz_cli_reset_) {
      const auto reset_result = resetGazeboObjectsWithGzCli(goal_handle);
      if (!reset_result.success || reset_result.canceled) {
        return reset_result;
      }
    }

    const bool beverage_node_reset = reset_world_on_start_ && !use_gz_cli_reset_;
    std::vector<std::string> args{
      ros2_executable_,
      "launch",
      "--noninteractive",
      "--show-all-subprocesses-output",
      beverage_launch_package_,
      beverage_launch_file_,
      "ingredient_model:=" + run.ingredient_model,
      std::string("reset_world_on_start:=") + (beverage_node_reset ? "true" : "false"),
    };
    if (!start_step_.empty()) {
      args.push_back("start_step:=" + start_step_);
    }
    if (!end_step_.empty()) {
      args.push_back("end_step:=" + end_step_);
    }

    RCLCPP_INFO(get_logger(), "Starting beverage test process: %s", joinCommandForLog(args).c_str());

    int output_pipe[2];
    if (pipe(output_pipe) != 0) {
      return ProcessResult{false, false, "failed to create beverage test process output pipe"};
    }

    const int flags = fcntl(output_pipe[0], F_GETFL, 0);
    if (flags >= 0) {
      fcntl(output_pipe[0], F_SETFL, flags | O_NONBLOCK);
    }

    const pid_t pid = fork();
    if (pid < 0) {
      close(output_pipe[0]);
      close(output_pipe[1]);
      return ProcessResult{false, false, "failed to fork beverage test process"};
    }

    if (pid == 0) {
      setpgid(0, 0);
      close(output_pipe[0]);
      dup2(output_pipe[1], STDOUT_FILENO);
      dup2(output_pipe[1], STDERR_FILENO);
      if (output_pipe[1] > STDERR_FILENO) {
        close(output_pipe[1]);
      }

      std::vector<char *> argv;
      argv.reserve(args.size() + 1);
      for (auto & arg : args) {
        argv.push_back(const_cast<char *>(arg.c_str()));
      }
      argv.push_back(nullptr);
      execvp(argv[0], argv.data());
      std::fprintf(stderr, "failed to exec %s: %s\n", argv[0], std::strerror(errno));
      _exit(127);
    }

    close(output_pipe[1]);
    auto finish = [&](ProcessResult result) {
      close(output_pipe[0]);
      return result;
    };

    setpgid(pid, pid);
    std::string process_output_tail;
    bool saw_success_marker = false;
    bool saw_failure_marker = false;
    const auto start_time = std::chrono::steady_clock::now();
    while (rclcpp::ok()) {
      readAvailableProcessOutput(
        output_pipe[0], process_output_tail, saw_success_marker, saw_failure_marker);

      int status = 0;
      const pid_t wait_result = waitpid(pid, &status, WNOHANG);
      if (wait_result == pid) {
        readAvailableProcessOutput(
          output_pipe[0], process_output_tail, saw_success_marker, saw_failure_marker);

        if (saw_failure_marker) {
          return finish(ProcessResult{
            false,
            false,
            "beverage test launch reported child process failure for item '" + run.item_name + "'"});
        }
        if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
          if (saw_success_marker) {
            return finish(ProcessResult{true, false, "beverage test process completed"});
          }
          return finish(ProcessResult{
            false,
            false,
            "beverage test launch exited without success marker for item '" + run.item_name + "'"});
        }
        if (WIFEXITED(status)) {
          return finish(ProcessResult{
            false,
            false,
            "beverage test process exited with code " + std::to_string(WEXITSTATUS(status))});
        }
        if (WIFSIGNALED(status)) {
          return finish(ProcessResult{
            false,
            false,
            "beverage test process terminated by signal " + std::to_string(WTERMSIG(status))});
        }
        return finish(ProcessResult{false, false, "beverage test process failed"});
      }
      if (wait_result < 0 && errno != EINTR) {
        return finish(ProcessResult{false, false, "failed while waiting for beverage test process"});
      }

      if (goal_handle->is_canceling()) {
        terminateProcessGroup(pid);
        return finish(ProcessResult{false, true, "manufacture canceled; beverage test process stopped"});
      }

      if (command_timeout_sec_ > 0.0) {
        const auto elapsed =
          std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time).count();
        if (elapsed > command_timeout_sec_) {
          terminateProcessGroup(pid);
          return finish(ProcessResult{false, false, "beverage test process timed out"});
        }
      }

      std::this_thread::sleep_for(200ms);
    }

    terminateProcessGroup(pid);
    return finish(ProcessResult{false, true, "ROS shutdown requested; beverage test process stopped"});
  }

  void terminateProcessGroup(pid_t pid) const
  {
    kill(-pid, SIGINT);
    for (int i = 0; i < 25; ++i) {
      int status = 0;
      const pid_t wait_result = waitpid(pid, &status, WNOHANG);
      if (wait_result == pid) {
        return;
      }
      std::this_thread::sleep_for(200ms);
    }

    kill(-pid, SIGTERM);
    for (int i = 0; i < 10; ++i) {
      int status = 0;
      const pid_t wait_result = waitpid(pid, &status, WNOHANG);
      if (wait_result == pid) {
        return;
      }
      std::this_thread::sleep_for(200ms);
    }

    kill(-pid, SIGKILL);
    int status = 0;
    waitpid(pid, &status, 0);
  }

  void publishStatus(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const std::string & status) const
  {
    auto feedback = std::make_shared<Manifacture::Feedback>();
    feedback->status = status;
    goal_handle->publish_feedback(feedback);
    RCLCPP_INFO(get_logger(), "%s", status.c_str());
  }

  void finishAborted(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const std::string & message) const
  {
    auto result = std::make_shared<Manifacture::Result>();
    result->success = false;
    result->message = message;
    goal_handle->abort(result);
    RCLCPP_ERROR(get_logger(), "%s", message.c_str());
  }

  void finishCanceled(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const std::string & message) const
  {
    auto result = std::make_shared<Manifacture::Result>();
    result->success = false;
    result->message = message;
    goal_handle->canceled(result);
    RCLCPP_WARN(get_logger(), "%s", message.c_str());
  }

  std::string action_name_;
  std::string ros2_executable_;
  std::string gz_executable_;
  std::string beverage_launch_package_;
  std::string beverage_launch_file_;
  std::string hotdog_launch_package_;
  std::string hotdog_launch_file_;
  bool hotdog_use_sim_time_;
  bool reset_world_on_start_;
  bool use_gz_cli_reset_;
  std::string gazebo_set_pose_service_;
  int gazebo_reset_timeout_ms_;
  double gazebo_reset_settle_sec_;
  std::string start_step_;
  std::string end_step_;
  double command_timeout_sec_;
  std::string execution_backend_;
  std::string hotdog_task_executable_;
  std::string drink_task_executable_;
  int scenario_step_delay_ms_;
  rclcpp_action::Server<Manifacture>::SharedPtr action_server_;
  mutable std::mutex active_goal_mutex_;
  bool active_goal_{false};
};
}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<ManifactureActionServer>());
  rclcpp::shutdown();
  return 0;
}
