// safety_check.hpp
// Phase 1 W1: alarm 패턴 (Nav2 컨벤션 일치).
// Phase 2 W4 후속 (RPi 연동 직전): /battery_state 통합.
// A 트랙 (Phase 후속): /scan 거리 임계 통합.
//
// === SUCCESS/FAILURE 시맨틱 ===
//   SUCCESS = 위험 발견됨 → ReactiveFallback 루트가 즉시 차단 (funnel 멈춤)
//   FAILURE = 위험 없음   → 다음 자식(EmotionMonitor / cafe_funnel)으로 진행
//
// 즉 정상 운영 시 FAILURE를 반환해야 한다 (직관 반대 주의).
//
// === 입력 ===
//   /battery_state (sensor_msgs/BatteryState, 1Hz)
//     vicpinky_bringup이 발행 (CLAUDE.md §4.1):
//       - 7S Li-ion: 21.0V (컷오프) ~ 29.4V (만충)
//       - percentage 필드: 0.0~1.0 (clamp)
//     percentage < battery_min(기본 0.20) → SUCCESS (저전압 alarm)
//
//   /scan (sensor_msgs/LaserScan)
//     vicpinky_bringup이 RPLiDAR로 발행. 360도 거리 측정.
//     scan_min_range(기본 0.05m) ~ scan_min_dist(기본 1.0m) 범위 내 obstacle
//     1개라도 있으면 SUCCESS (intimate space 침입). 사람/벽 구분 없음.
//
// === 가드 조합 ===
//   배터리 alarm OR scan alarm → SUCCESS
//   둘 다 정상 → FAILURE
//
// === 미수신 정책 ===
//   /battery_state 미수신 → 안전 측 OK (FAILURE)
//   /scan 미수신          → 안전 측 OK (FAILURE)
//   라이브 미연결 환경에서 funnel 차단 안 함. RPi 연결 후엔 정상 평가.

#ifndef DOBI_NPC_BT__SAFETY_CHECK_HPP_
#define DOBI_NPC_BT__SAFETY_CHECK_HPP_

#include <atomic>
#include <cmath>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include "behaviortree_cpp/condition_node.h"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/battery_state.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"

namespace dobi_npc_bt
{

class SafetyCheck : public BT::ConditionNode
{
public:
  SafetyCheck(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::ConditionNode(name, config),
    node_(std::move(ros_node)),
    battery_pct_(-1.0f),  // 초기값: 메시지 못 받았음
    last_warned_low_(false),
    last_warned_scan_(false),
    scan_received_(false),
    scan_min_obs_dist_(std::numeric_limits<float>::infinity())
  {
    sub_battery_ = node_->create_subscription<sensor_msgs::msg::BatteryState>(
      "/battery_state", rclcpp::QoS(10).best_effort(),
      [this](sensor_msgs::msg::BatteryState::SharedPtr msg) {
        battery_pct_.store(msg->percentage);
      });

    // /scan 은 LiDAR 기본 BEST_EFFORT, KEEP_LAST(5) — Nav2 표준과 일치.
    sub_scan_ = node_->create_subscription<sensor_msgs::msg::LaserScan>(
      "/scan", rclcpp::QoS(5).best_effort(),
      [this](sensor_msgs::msg::LaserScan::SharedPtr msg) {
        on_scan(msg);
      });
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<double>(
        "battery_min", 0.20,
        "최소 배터리 percentage (0.0~1.0). 미만 시 alarm SUCCESS"),
      BT::InputPort<double>(
        "scan_min_dist", 1.0,
        "scan 임계 거리 (m). 이 거리 내 obstacle 발견 시 alarm SUCCESS"),
      BT::InputPort<double>(
        "scan_min_range", 0.05,
        "LiDAR self-noise 무시 거리 (m). 이보다 가까운 측정값은 무시"),
      BT::InputPort<std::string>(
        "scan_alarm_enabled", "true",
        "/scan 가드 활성 여부 ('true'|'false'|'1'|'0'). 비활성 시 배터리만 평가"),
    };
  }

  BT::NodeStatus tick() override
  {
    double battery_min = 0.20;
    double scan_min_dist = 1.0;
    std::string scan_enabled_str = "true";
    getInput<double>("battery_min", battery_min);
    getInput<double>("scan_min_dist", scan_min_dist);
    getInput<std::string>("scan_alarm_enabled", scan_enabled_str);
    const bool scan_enabled =
      (scan_enabled_str == "true" || scan_enabled_str == "1" ||
       scan_enabled_str == "True" || scan_enabled_str == "TRUE");

    // === 1. 배터리 가드 ===
    const float pct = battery_pct_.load();
    bool battery_alarm = false;
    if (pct >= 0.0f && pct < static_cast<float>(battery_min)) {
      battery_alarm = true;
      if (!last_warned_low_) {
        RCLCPP_WARN(node_->get_logger(),
          "[SafetyCheck] battery low: %.1f%% < %.1f%% → alarm",
          pct * 100.0f, battery_min * 100.0f);
        last_warned_low_ = true;
      }
    } else if (last_warned_low_ && pct >= 0.0f) {
      RCLCPP_INFO(node_->get_logger(),
        "[SafetyCheck] battery recovered: %.1f%% → normal",
        pct * 100.0f);
      last_warned_low_ = false;
    }

    // === 2. scan 가드 ===
    bool scan_alarm = false;
    float scan_min_obs;
    bool scan_seen;
    {
      std::lock_guard<std::mutex> lock(scan_mtx_);
      scan_seen = scan_received_;
      scan_min_obs = scan_min_obs_dist_;
    }
    if (scan_enabled && scan_seen &&
        scan_min_obs < static_cast<float>(scan_min_dist))
    {
      scan_alarm = true;
      if (!last_warned_scan_) {
        RCLCPP_WARN(node_->get_logger(),
          "[SafetyCheck] obstacle within %.2fm < %.2fm → alarm",
          scan_min_obs, scan_min_dist);
        last_warned_scan_ = true;
      }
    } else if (last_warned_scan_) {
      RCLCPP_INFO(node_->get_logger(),
        "[SafetyCheck] scan clear: nearest=%.2fm ≥ %.2fm → normal",
        std::isfinite(scan_min_obs) ? scan_min_obs : -1.0f,
        scan_min_dist);
      last_warned_scan_ = false;
    }

    // === 3. 가드 조합 — OR ===
    if (battery_alarm || scan_alarm) {
      return BT::NodeStatus::SUCCESS;
    }
    return BT::NodeStatus::FAILURE;
  }

private:
  void on_scan(const sensor_msgs::msg::LaserScan::SharedPtr msg)
  {
    // 가장 가까운 obstacle 거리 계산. min_range 이하 / NaN / inf 무시.
    double scan_min_range = 0.05;
    getInput<double>("scan_min_range", scan_min_range);
    const float min_r = static_cast<float>(scan_min_range);
    const float msg_range_max = msg->range_max > 0.0f
      ? msg->range_max
      : std::numeric_limits<float>::infinity();

    float nearest = std::numeric_limits<float>::infinity();
    for (const float r : msg->ranges) {
      if (!std::isfinite(r)) continue;
      if (r < min_r) continue;
      if (r > msg_range_max) continue;
      if (r < nearest) nearest = r;
    }

    std::lock_guard<std::mutex> lock(scan_mtx_);
    scan_received_ = true;
    scan_min_obs_dist_ = nearest;
  }

  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<sensor_msgs::msg::BatteryState>::SharedPtr sub_battery_;
  rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr sub_scan_;

  std::atomic<float> battery_pct_;
  bool last_warned_low_;
  bool last_warned_scan_;

  std::mutex scan_mtx_;
  bool scan_received_;          // 한 번이라도 /scan 수신했나
  float scan_min_obs_dist_;     // 최근 scan 의 가장 가까운 obstacle 거리
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__SAFETY_CHECK_HPP_
