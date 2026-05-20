#include <functional>
#include <atomic>
#include <cerrno>
#include <fcntl.h>
#include <memory>
#include <arpa/inet.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <thread>
#include <unistd.h>
#include <sstream>
#include <string>

#include "controller_status_msgs/msg/status.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/string.hpp"
#include "std_srvs/srv/trigger.hpp"

class TubiControllerNode : public rclcpp::Node
{
public:
  TubiControllerNode()
  : Node("tubi_controller"), request_id_(0), running_(true), server_fd_(-1)
  {
    const auto controller_name = this->declare_parameter<std::string>(
      "controller_name", "tubi_controller");
    control_service_host_ = this->declare_parameter<std::string>(
      "control_service_host", "127.0.0.1");
    control_service_port_ = this->declare_parameter<int>("control_service_port", 9001);
    tcp_timeout_sec_ = this->declare_parameter<double>("tcp_timeout_sec", 3.0);
    service_listener_host_ = this->declare_parameter<std::string>(
      "service_listener_host", "0.0.0.0");
    service_listener_port_ = this->declare_parameter<int>("service_listener_port", 9005);
    control_status_topic_ = this->declare_parameter<std::string>(
      "control_status_topic", "/control_service/status");
    status_publisher_ = this->create_publisher<controller_status_msgs::msg::Status>(
      "/tubi_controller/status", 10);
    control_service_status_publisher_ = this->create_publisher<std_msgs::msg::String>(
      control_status_topic_, 10);
    health_service_ = this->create_service<std_srvs::srv::Trigger>(
      "/tubi_controller/health_check",
      std::bind(
        &TubiControllerNode::handle_health_check,
        this,
        std::placeholders::_1,
        std::placeholders::_2));
    server_thread_ = std::thread([this]() { this->run_tcp_server(); });
    RCLCPP_INFO(this->get_logger(), "%s started", controller_name.c_str());
    RCLCPP_INFO(
      this->get_logger(),
      "bridging tubi_controller status to control_service TCP %s:%d",
      control_service_host_.c_str(),
      control_service_port_);
    RCLCPP_INFO(
      this->get_logger(),
      "bridging control_service TCP %s:%d to ROS topic %s",
      service_listener_host_.c_str(),
      service_listener_port_,
      control_status_topic_.c_str());
  }

  ~TubiControllerNode() override
  {
    running_ = false;
    if (server_fd_ >= 0) {
      shutdown(server_fd_, SHUT_RDWR);
      close(server_fd_);
    }
    if (server_thread_.joinable()) {
      server_thread_.join();
    }
  }

private:
  static constexpr unsigned char STX = 0x02;
  static constexpr unsigned char STATUS_CMD = 0x10;
  static constexpr unsigned char ETX = 0x03;
  static constexpr size_t FRAME_SIZE = 4;

  void handle_health_check(
    const std::shared_ptr<std_srvs::srv::Trigger::Request>,
    std::shared_ptr<std_srvs::srv::Trigger::Response> response)
  {
    const auto request_id = ++request_id_;

    RCLCPP_INFO(this->get_logger(), "received health check request_id=%u", request_id);

    controller_status_msgs::msg::Status message;
    message.request_id = request_id;
    status_publisher_->publish(message);
    send_status_to_control_service(request_id);

    RCLCPP_INFO(
      this->get_logger(),
      "published status request_id=%u targets=[dual_arm_controller,control_service]",
      request_id);

    response->success = true;
    response->message = "tubi_controller health status published";
  }

  void send_status_to_control_service(unsigned int seq)
  {
    addrinfo hints {};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    addrinfo * result = nullptr;
    const auto port = std::to_string(control_service_port_);
    const int error = getaddrinfo(control_service_host_.c_str(), port.c_str(), &hints, &result);
    if (error != 0) {
      RCLCPP_WARN(
        this->get_logger(),
        "failed to resolve control_service %s:%d: %s",
        control_service_host_.c_str(),
        control_service_port_,
        gai_strerror(error));
      return;
    }

    int sock = -1;
    for (auto * rp = result; rp != nullptr; rp = rp->ai_next) {
      sock = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
      if (sock < 0) {
        continue;
      }

      if (connect_with_timeout(sock, rp->ai_addr, rp->ai_addrlen)) {
        break;
      }

      close(sock);
      sock = -1;
    }
    freeaddrinfo(result);

    if (sock < 0) {
      RCLCPP_WARN(
        this->get_logger(),
        "failed to connect control_service %s:%d",
        control_service_host_.c_str(),
        control_service_port_);
      return;
    }

    const unsigned char frame[FRAME_SIZE] = {
      STX,
      STATUS_CMD,
      static_cast<unsigned char>(seq & 0xFF),
      ETX};
    const auto sent = send(sock, frame, FRAME_SIZE, 0);
    close(sock);

    if (sent != static_cast<ssize_t>(FRAME_SIZE)) {
      RCLCPP_WARN(this->get_logger(), "failed to send STATUS seq=%u to control_service", seq);
      return;
    }

    RCLCPP_INFO(this->get_logger(), "sent STATUS seq=%u to control_service", seq);
  }

  bool connect_with_timeout(int sock, const sockaddr * address, socklen_t address_len)
  {
    const int original_flags = fcntl(sock, F_GETFL, 0);
    if (original_flags < 0) {
      return false;
    }

    if (fcntl(sock, F_SETFL, original_flags | O_NONBLOCK) < 0) {
      return false;
    }

    const int result = connect(sock, address, address_len);
    if (result == 0) {
      fcntl(sock, F_SETFL, original_flags);
      return true;
    }

    if (errno != EINPROGRESS) {
      fcntl(sock, F_SETFL, original_flags);
      return false;
    }

    fd_set write_fds;
    FD_ZERO(&write_fds);
    FD_SET(sock, &write_fds);

    timeval timeout {};
    timeout.tv_sec = static_cast<time_t>(tcp_timeout_sec_);
    timeout.tv_usec = static_cast<suseconds_t>(
      (tcp_timeout_sec_ - static_cast<double>(timeout.tv_sec)) * 1000000.0);

    const int ready = select(sock + 1, nullptr, &write_fds, nullptr, &timeout);
    if (ready <= 0) {
      fcntl(sock, F_SETFL, original_flags);
      return false;
    }

    int socket_error = 0;
    socklen_t socket_error_len = sizeof(socket_error);
    if (getsockopt(sock, SOL_SOCKET, SO_ERROR, &socket_error, &socket_error_len) < 0) {
      fcntl(sock, F_SETFL, original_flags);
      return false;
    }

    fcntl(sock, F_SETFL, original_flags);
    return socket_error == 0;
  }

  void run_tcp_server()
  {
    server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd_ < 0) {
      RCLCPP_WARN(this->get_logger(), "failed to create tubi_controller TCP bridge socket");
      return;
    }

    int opt = 1;
    setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in address {};
    address.sin_family = AF_INET;
    address.sin_port = htons(static_cast<uint16_t>(service_listener_port_));
    if (service_listener_host_ == "0.0.0.0") {
      address.sin_addr.s_addr = INADDR_ANY;
    } else if (inet_pton(AF_INET, service_listener_host_.c_str(), &address.sin_addr) != 1) {
      RCLCPP_WARN(
        this->get_logger(),
        "invalid service listener host %s",
        service_listener_host_.c_str());
      return;
    }

    if (bind(server_fd_, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
      RCLCPP_WARN(
        this->get_logger(),
        "failed to bind tubi_controller TCP bridge %s:%d",
        service_listener_host_.c_str(),
        service_listener_port_);
      return;
    }

    if (listen(server_fd_, 8) < 0) {
      RCLCPP_WARN(this->get_logger(), "failed to listen on tubi_controller TCP bridge");
      return;
    }

    while (running_) {
      const int client_fd = accept(server_fd_, nullptr, nullptr);
      if (client_fd < 0) {
        if (running_) {
          RCLCPP_WARN(this->get_logger(), "failed to accept control_service TCP client");
        }
        continue;
      }

      handle_tcp_client(client_fd);
      close(client_fd);
    }
  }

  void handle_tcp_client(int client_fd)
  {
    while (running_) {
      unsigned char frame[FRAME_SIZE] {};
      size_t received = 0;
      while (received < FRAME_SIZE) {
        const auto count = recv(client_fd, frame + received, FRAME_SIZE - received, 0);
        if (count <= 0) {
          return;
        }
        received += static_cast<size_t>(count);
      }

      if (frame[0] != STX || frame[1] != STATUS_CMD || frame[3] != ETX) {
        RCLCPP_WARN(this->get_logger(), "invalid control_service TCP frame");
        continue;
      }

      publish_control_service_status(frame[2]);
    }
  }

  void publish_control_service_status(unsigned int seq)
  {
    std_msgs::msg::String message;
    std::ostringstream payload;
    payload << "{\"source\":\"control_service\","
            << "\"target\":\"tubi_controller\","
            << "\"event\":\"health_status\","
            << "\"status\":\"ok\","
            << "\"request_id\":" << seq << "}";
    message.data = payload.str();
    control_service_status_publisher_->publish(message);
    RCLCPP_INFO(
      this->get_logger(),
      "published control_service STATUS seq=%u to %s",
      seq,
      control_status_topic_.c_str());
  }

  rclcpp::Publisher<controller_status_msgs::msg::Status>::SharedPtr status_publisher_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr control_service_status_publisher_;
  rclcpp::Service<std_srvs::srv::Trigger>::SharedPtr health_service_;
  std::string control_service_host_;
  int control_service_port_;
  double tcp_timeout_sec_;
  std::string service_listener_host_;
  int service_listener_port_;
  std::string control_status_topic_;
  unsigned int request_id_;
  std::atomic<bool> running_;
  int server_fd_;
  std::thread server_thread_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<TubiControllerNode>());
  rclcpp::shutdown();
  return 0;
}
