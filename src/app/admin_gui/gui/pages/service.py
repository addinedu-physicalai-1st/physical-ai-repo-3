from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from style import BG, CYAN, ERROR, ORANGE, PRIMARY, SUCCESS, TEXT2, TEXT3, WARNING

from gui.common import (
    card_frame,
    make_table,
    mkbadge,
    mklbl,
    page_header,
    set_table_rows,
    wrap_scroll,
)


ORDER_STATUS_SUMMARY = [
]

PAYMENT_STATUS_SUMMARY = [
]

RECENT_ORDERS = [
]

TABLE_STATUS = [
]


class ServiceManagementPage(QWidget):
    def __init__(self, realtime=None):
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
        self.order_table = make_table(
            ['주문', '채널', '수령', '테이블', '주문 상태', '결제', '금액', '갱신'],
            RECENT_ORDERS,
        )
        order_layout.addWidget(self.order_table)
        content_layout.addWidget(order_card)

        table_card, table_layout = card_frame('테이블 관리')
        self.table_grid = QGridLayout()
        self.table_grid.setSpacing(12)
        self._set_table_cards(TABLE_STATUS)
        table_layout.addLayout(self.table_grid)
        content_layout.addWidget(table_card)

        bl.addWidget(wrap_scroll(content), 1)
        if realtime is not None:
            realtime.orders_updated.connect(self.update_orders)
            realtime.tables_updated.connect(self.update_tables)

    def update_orders(self, orders):
        rows = []
        for order in orders:
            table_number = order.get('table_number')
            rows.append([
                f"#{order.get('order_id', '')}",
                order.get('order_source', order.get('channel', '')),
                order.get('receive_type', ''),
                f"{table_number}번" if table_number else '-',
                order.get('order_status', ''),
                order.get('payment_status', ''),
                self._format_price(order.get('total_price', order.get('total', 0))),
                order.get('updated_at', order.get('updated', '')),
            ])
        set_table_rows(self.order_table, rows)

    def update_tables(self, tables):
        self._clear_table_grid()
        self._set_table_cards(tables)

    def _set_table_cards(self, tables):
        if not tables:
            empty_label = mklbl('비어 있음', color=TEXT2)
            empty_label.setMinimumHeight(96)
            self.table_grid.addWidget(empty_label, 0, 0)
            return

        for i, table in enumerate(tables):
            if isinstance(table, dict):
                number = table.get('table_number', table.get('id', ''))
                status = table.get('status', 'empty')
                order_id = table.get('active_order_id')
                detail = f"주문 #{order_id}" if order_id else ('대기 가능' if status == 'empty' else '사용 중')
            else:
                number, status, detail = table
            self.table_grid.addWidget(self._table_card(number, status, detail), i // 4, i % 4)

    def _table_card(self, number, status, detail):
        color = ORANGE if status == 'occupied' else SUCCESS
        label = '사용 중' if status == 'occupied' else '비어 있음'

        card, lay = card_frame()
        card.setMinimumSize(160, 112)
        top = QHBoxLayout()
        top.addWidget(mklbl(f'{number}번 테이블', 15, True))
        top.addStretch()
        top.addWidget(mkbadge(label, color))
        lay.addLayout(top)
        lay.addWidget(mklbl(detail, color=TEXT2))
        return card

    def _clear_table_grid(self):
        while self.table_grid.count():
            item = self.table_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _format_price(self, value):
        return f"{int(value):,}원" if isinstance(value, int) else str(value)
