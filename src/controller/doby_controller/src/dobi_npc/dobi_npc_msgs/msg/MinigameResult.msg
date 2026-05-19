# 미니게임 결과 (Castro-González 2016 RPS 표준)
# 발행: rps_game_node
# 구독: BT의 Minigame action client

std_msgs/Header header

string game_id              # "rps" (향후 다른 게임 추가 가능)
uint32 rounds_played
uint32 customer_wins
uint32 robot_wins
uint32 ties

# Castro-González 정신: 70% 고객 승리율 추적
float32 customer_win_rate   # 0.0 ~ 1.0 (목표: 0.7)

float32 duration_sec
bool completed              # 끝까지 진행 / 도중 abort
