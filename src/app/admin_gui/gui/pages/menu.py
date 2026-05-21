from style import ERROR, PRIMARY, WARNING
from gui.common import SimpleTablePage, mkbtn
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from seed import MENU_LIST


class MenuPage(SimpleTablePage):
    def __init__(self, realtime=None):
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
        if realtime is not None:
            realtime.products_updated.connect(self.update_products)

    def update_products(self, products):
        self.set_rows([self._product_row(product) for product in products])

    def _product_row(self, product):
        product_id = product.get('product_id', product.get('id', ''))
        price = product.get('price', 0)
        options = product.get('options', [])
        allergies = product.get('allergies', product.get('allergy', []))
        option_text = self._join_values(options, ('option_name', 'name'))
        allergy_text = self._join_values(allergies, ('name',))
        return [
            f"M{int(product_id):03d}" if isinstance(product_id, int) else product_id,
            product.get('name', ''),
            f"{int(price):,}원" if isinstance(price, int) else price,
            allergy_text or '없음',
            option_text or '-',
        ]

    def _join_values(self, values, keys):
        if not isinstance(values, list):
            return str(values) if values else ''
        result = []
        for value in values:
            if isinstance(value, dict):
                for key in keys:
                    if value.get(key):
                        result.append(str(value[key]))
                        break
            elif value:
                result.append(str(value))
        return ' / '.join(result)
