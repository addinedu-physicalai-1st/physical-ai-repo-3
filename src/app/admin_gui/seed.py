from style import PRIMARY, SUCCESS, TEXT2

# map.py data
MAP_FACILITIES = [
    ('커피트럭', '#92400E', 150, 120),
    ('테이블 A', '#1D4ED8', 270, 180),
    ('테이블 B', '#1D4ED8', 360, 250),
    ('로봇 대기', '#059669', 210, 270),
]

MAP_LIST = [
    ['1층 로비'],
    ['2층 테라스'],
]

MAP_PROPERTIES = {
    'name': '1층 로비',
    'location': '서울 강남구 테헤란로 123',
    'width': '20.0 m',
    'height': '15.0 m'
}

# menu.py data
MENU_LIST = [
    ['M001', '아메리카노', '3,500원', '없음', '샷추가 / 기본 얼음', '대표'],
    ['M002', '카페라떼', '4,000원', '우유', '샷추가 / 저지방 / 기본 얼음', ''],
    ['M003', '카라멜 마끼아또', '4,500원', '우유, 대두', '샷추가 / 크러쉬드 아이스', '대표'],
]

# monitoring.py & dashboard.py data
ROBOT_LIST = ['ROB-01', 'ROB-02', 'ROB-03']

ROBOT_STATUS_LIST = [
    ('ROB-01', '정상대기', 87, '양호(5G)', '대기 중', '정상'),
    ('ROB-02', '충전중', 54, '보통(4G)', '충전 중', '정상'),
    ('ROB-03', '오프라인', 100, '없음', '대기 중', '정상'),
]

DASHBOARD_STATS = [
    ('현재 모드', '대기', PRIMARY),
    ('배터리', '87%', SUCCESS),
    ('안전 알람', '없음', SUCCESS),
    ('Reject 사유', '-', TEXT2),
]

# system_log.py data
SYSTEM_LOGS = [
    ['10:00:00', 'INFO', 'SYSTEM', 'task', '서빙 태스크 시작'],
    ['10:01:12', 'WARN', 'ROB-02', '하드웨어', '배터리 경고'],
    ['10:03:24', 'INFO', 'ROB-01', '주행', '목적지 도착'],
]

# anomaly.py data
ANOMALY_LIST = [
    ['통신 이상', 'ROB-02', '05/20 10:12:00', '통신 지연 감지', '미확인'],
    ['로봇 파손', 'ROB-03', '05/20 10:15:00', '전면 파손 이벤트', '확인됨'],
]
