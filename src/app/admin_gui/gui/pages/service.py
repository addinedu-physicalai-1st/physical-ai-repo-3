from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from style import BG, CYAN, ERROR, ORANGE, PRIMARY, SUCCESS, TEXT2, TEXT3, WARNING

from gui.common import (
    card_frame,
    hdivider,
    make_table,
    mkbadge,
    mklbl,
    page_header,
    wrap_scroll,
)


ORDER_STATUS_SUMMARY = [
    ('PENDING', '접수 대기', 3, WARNING),
    ('ACCEPTED', '접수 완료', 4, PRIMARY),
    ('PREPARING', '제조 중', 5, ORANGE),
    ('READY', '픽업 대기', 2, CYAN),
    ('COMPLETED', '완료', 18, SUCCESS),
    ('CANCELED', '취소', 1, ERROR),
]

PAYMENT_STATUS_SUMMARY = [
    ('PENDING', '결제 대기', 3, WARNING),
    ('PAID', '결제 완료', 27, SUCCESS),
    ('CANCELED', '결제 취소', 1, TEXT3),
    ('REFUNDED', '환불', 2, ERROR),
]

RECENT_ORDERS = [
    ['#1042', 'TABLE', 'DINE_IN', '2번', 'PREPARING', 'PAID', '12,500원', '10:18'],
    ['#1041', 'COUNTER', 'TAKE_OUT', '-', 'READY', 'PAID', '5,000원', '10:15'],
    ['#1040', 'TABLE', 'DINE_IN', '4번', 'ACCEPTED', 'PENDING', '18,000원', '10:12'],
    ['#1039', 'COUNTER', 'PENDING', '-', 'PENDING', 'PENDING', '3,500원', '10:10'],
    ['#1038', 'TABLE', 'DINE_IN', '1번', 'COMPLETED', 'PAID', '9,000원', '10:03'],
]

TABLE_STATUS = [
    (1, 'occupied', '주문 #1038', '0.000', '0.000'),
    (2, 'occupied', '주문 #1042', '0.000', '0.000'),
    (3, 'empty', '대기 가능', '0.000', '0.000'),
    (4, 'occupied', '주문 #1040', '0.000', '0.000'),
]


class ServiceManagementPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header('서비스 관리', '주문 상태와 테이블 점유 상태 모니터링'))
        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.setSpacing(16)
        root.addWidget(body, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        order_card, order_layout = card_frame('주문 관리')
        order_layout.addWidget(make_table(
            ['주문', '채널', '수령', '테이블', '주문 상태', '결제', '금액', '갱신'],
            RECENT_ORDERS,
        ))
        content_layout.addWidget(order_card)

        table_card, table_layout = card_frame('테이블 관리')
        table_grid = QGridLayout()
        table_grid.setSpacing(12)
        for i, table in enumerate(TABLE_STATUS):
            table_grid.addWidget(self._table_card(*table), i // 4, i % 4)
        table_layout.addLayout(table_grid)
        content_layout.addWidget(table_card)

        bl.addWidget(wrap_scroll(content), 1)

    def _table_card(self, number, status, detail, pos_x, pos_y):
        color = ORANGE if status == 'occupied' else SUCCESS
        label = '사용 중' if status == 'occupied' else '비어있음'

        card, lay = card_frame()
        card.setMinimumSize(160, 130)
        top = QHBoxLayout()
        top.addWidget(mklbl(f'{number}번 테이블', 15, True))
        top.addStretch()
        top.addWidget(mkbadge(label, color))
        lay.addLayout(top)
        lay.addWidget(mklbl(detail, color=TEXT2))
        lay.addWidget(mklbl(f'좌표 ({pos_x}, {pos_y})', 11, color=TEXT3))
        return card
