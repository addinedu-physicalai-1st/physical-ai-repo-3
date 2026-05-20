import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import SYSTEM_LOGS
from style import ERROR
from gui.common import SimpleTablePage, mkobtn


class SystemLogPage(SimpleTablePage):
    def __init__(self):
        super().__init__(
            '시스템 로그',
            '로봇 및 시스템 이벤트 로그 조회',
            [mkobtn('로그 초기화', ERROR)],
            ['시각', '레벨', '로봇', '분류', '메시지'],
            SYSTEM_LOGS,
        )
