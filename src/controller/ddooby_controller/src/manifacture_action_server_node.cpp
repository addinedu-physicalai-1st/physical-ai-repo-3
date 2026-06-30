#include <chrono>
#include <array>
#include <cerrno>
#include <csignal>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <cstring>
#include <memory>
#include <mutex>
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

using Manifacture = custom_msg::action::Manifacture;
using GoalHandleManifacture = rclcpp_action::ServerGoalHandle<Manifacture>;

struct ManufactureTaskRun
{
  std::string item_name;
  std::string task_name;
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

bool taskNameForItem(const std::string & item_name, std::string & task_name)
{
  const std::string lowered = toLowerAscii(item_name);
  if (lowered == "hotdog" || lowered == "hot dog" ||
    containsAny(lowered, {"new york", "핫도그", "뉴욕"}))
  {
    task_name = "hotdog";
    return true;
  }
  if (lowered == "coke" || lowered == "cola" || containsAny(lowered, {"콜라"})) {
    task_name = "coke";
    return true;
  }
  if (lowered == "coffee" || containsAny(lowered, {"커피"})) {
    task_name = "coffee";
    return true;
  }
  return false;
}

std::string joinCommandForLog(const std::vector<std::string> & args)
{
  std::ostringstream stream;
  bool first = true;
  for (const auto & arg : args) {
    if (!first) {
      stream << ' ';
    }
    first = false;
    stream << arg;
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

void readAvailableProcessOutput(
  int output_fd,
  std::string & output_tail)
{
  char buffer[4096];
  while (true) {
    const ssize_t bytes_read = read(output_fd, buffer, sizeof(buffer));
    if (bytes_read > 0) {
      std::fwrite(buffer, 1, static_cast<size_t>(bytes_read), stdout);
      std::fflush(stdout);

      output_tail.append(buffer, static_cast<size_t>(bytes_read));
      trimProcessOutputTail(output_tail);
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
    hotdog_launch_package_ =
      declare_parameter<std::string>("hotdog_launch_package", "ddooby_controller");
    hotdog_launch_file_ =
      declare_parameter<std::string>("hotdog_launch_file", "hotdog_making.launch.py");
    hotdog_use_sim_time_ = declare_parameter<bool>("hotdog_use_sim_time", true);
    command_timeout_sec_ = declare_parameter<double>("command_timeout_sec", 0.0);

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
  ManifactureActionServer(const ManifactureActionServer &) = delete;
  ManifactureActionServer & operator=(const ManifactureActionServer &) = delete;

private:
  class ActiveGoalGuard
  {
  public:
    explicit ActiveGoalGuard(ManifactureActionServer & server)
    : server_(server)
    {
    }
    ActiveGoalGuard(const ActiveGoalGuard &) = delete;
    ActiveGoalGuard & operator=(const ActiveGoalGuard &) = delete;

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

    std::vector<ManufactureTaskRun> run_plan;
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
        finishCanceled(goal_handle, "manufacture canceled before next task run");
        return;
      }

      const auto & run = run_plan[index];
      std::ostringstream status;
      status << "manufacturing " << run.item_name << " with " << hotdog_launch_file_;
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
    std::vector<ManufactureTaskRun> & run_plan,
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

      std::string task_name;
      if (!taskNameForItem(item.name, task_name)) {
        error =
          "unsupported manufacture item '" + item.name +
          "': backend supports hotdog, coke, and coffee items only";
        return false;
      }

      for (int run_index = 1; run_index <= item.count; ++run_index) {
        run_plan.push_back(ManufactureTaskRun{
          item.name,
          task_name,
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

  CommandResult runCommandAndCollectOutput(
    const std::vector<std::string> & args,
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    double timeout_sec) const
  {
    std::array<int, 2> output_pipe{};
    if (pipe(output_pipe.data()) != 0) {
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
    const auto start_time = std::chrono::steady_clock::now();
    while (rclcpp::ok()) {
      readAvailableProcessOutput(output_pipe[0], output_tail);

      int status = 0;
      const pid_t wait_result = waitpid(pid, &status, WNOHANG);
      if (wait_result == pid) {
        readAvailableProcessOutput(output_pipe[0], output_tail);
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

      std::this_thread::sleep_for(std::chrono::milliseconds{100});
    }

    terminateProcessGroup(pid);
    return finish(CommandResult{false, true, -1, output_tail, "ROS shutdown requested"});
  }

  ProcessResult runManufactureTask(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const ManufactureTaskRun & run) const
  {
    return runManufacturingTaskLaunch(goal_handle, run);
  }

  ProcessResult runManufacturingTaskLaunch(
    const std::shared_ptr<GoalHandleManifacture> & goal_handle,
    const ManufactureTaskRun & run) const
  {
    std::vector<std::string> args{
      ros2_executable_,
      "launch",
      "--noninteractive",
      "--show-all-subprocesses-output",
      hotdog_launch_package_,
      hotdog_launch_file_,
      "task:=" + run.task_name,
      std::string("use_sim_time:=") + (hotdog_use_sim_time_ ? "true" : "false"),
    };

    const std::string success_marker = run.task_name == "hotdog" ?
      "New York hotdog assembly completed" :
      "Beverage " + run.task_name + " serving completed";

    RCLCPP_INFO(
      get_logger(),
      "Starting manufacture process for %s: %s",
      run.task_name.c_str(),
      joinCommandForLog(args).c_str());
    const auto command_result = runCommandAndCollectOutput(args, goal_handle, command_timeout_sec_);
    if (command_result.canceled) {
      return ProcessResult{false, true, "manufacture canceled while running " + run.task_name + " task"};
    }
    if (!command_result.success) {
      return ProcessResult{
        false,
        false,
        run.task_name + " manufacture failed for item '" + run.item_name + "': " +
          command_result.message};
    }
    if (command_result.output.find(success_marker) == std::string::npos) {
      return ProcessResult{
        false,
        false,
        run.task_name + " manufacture exited without completion marker for item '" + run.item_name + "'"};
    }

    return ProcessResult{true, false, run.task_name + " manufacture completed"};
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
      std::this_thread::sleep_for(std::chrono::milliseconds{200});
    }

    kill(-pid, SIGTERM);
    for (int i = 0; i < 10; ++i) {
      int status = 0;
      const pid_t wait_result = waitpid(pid, &status, WNOHANG);
      if (wait_result == pid) {
        return;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds{200});
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
  std::string hotdog_launch_package_;
  std::string hotdog_launch_file_;
  bool hotdog_use_sim_time_;
  double command_timeout_sec_;
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
