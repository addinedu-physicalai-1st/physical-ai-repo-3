import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import ANOMALY_LIST
from style import ERROR, SUCCESS, WARNING
from gui.common import SimpleTablePage, mkbtn


class AnomalyPage(SimpleTablePage):
    def __init__(self):
        super().__init__(
            '이상 상태 감지',
            '로봇 이상 알림 수신 및 확인 처리',
            [mkbtn('선택 확인 처리', SUCCESS), mkbtn('전체 확인', WARNING), mkbtn('확인된 항목 삭제', ERROR)],
            ['유형', '로봇', '발생시각', '상세', '상태'],
            ANOMALY_LIST,
        )
