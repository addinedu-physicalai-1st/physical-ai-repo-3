from style import ERROR, PRIMARY, WARNING
from gui.common import SimpleTablePage, mkbadge, mkbtn
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import MENU_LIST


class MenuPage(SimpleTablePage):
    def __init__(self):
        super().__init__(
            '상품 메뉴 관리',
            '음료 메뉴 등록·수정·삭제 및 대표 메뉴 지정',
            [
                mkbtn('+ 메뉴 추가'), 
                mkbtn('수정', WARNING), 
                mkbtn('삭제', ERROR)
            ],
            ['상품번호', '상품명', '가격', '알러지', '옵션'],
            MENU_LIST,
        )
