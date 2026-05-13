# MOCA

음성 주문, 상품 제조·서빙·정리, 고객 안내와 호객까지 수행하는 자율주행 카페 로봇 통합 서비스 프로젝트입니다.

## Core Features

1. **음성 기반 주문 시스템**
2. **로봇 기반 상품 제조·서빙 자동화**
3. **야외 고객 유치 및 고객 인터랙티브 서비스**

## Directory Structure

```
.
├── device
│   ├── cooking_controller
│   ├── dual_arm_controller
│   ├── interaction_controller
│   ├── serving_controller
│   ├── single_arm_controller
│   ├── table_monitor_controller
│   └── vic_pinky_controller
├── server
│   ├── business_db
│   ├── business_service
│   ├── control_service
│   ├── vision_service
│   └── web_service
└── ui
    ├── admin_gui
    └── order_vui
```