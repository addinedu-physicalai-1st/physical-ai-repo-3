from app.models.menu import AllergyInfo, MenuItem

MENU: list[MenuItem] = [
    MenuItem(id=1, name="아메리카노",     emoji="☕", price=3500, hot=True,  shot=True,  ice=True,  milk=False),
    MenuItem(id=2, name="카페라떼",       emoji="☕", price=4500, hot=True,  shot=True,  ice=True,  milk=True),
    MenuItem(id=3, name="카푸치노",       emoji="🫧", price=4500, hot=True,  shot=True,  ice=False, milk=True),
    MenuItem(id=4, name="바닐라라떼",     emoji="🌼", price=5000, hot=True,  shot=True,  ice=True,  milk=True),
    MenuItem(id=5, name="카라멜마키아토", emoji="🍮", price=5500, hot=True,  shot=True,  ice=True,  milk=True),
    MenuItem(id=6, name="말차라떼",       emoji="🍵", price=5500, hot=True,  shot=False, ice=True,  milk=True),
    MenuItem(id=7, name="딸기스무디",     emoji="🍓", price=6000, hot=False, shot=False, ice=True,  milk=False),
    MenuItem(id=8, name="치즈케이크",     emoji="🍰", price=7000, hot=False, shot=False, ice=False, milk=False),
]

ALLERGY: list[AllergyInfo] = [
    AllergyInfo(name="유제품", icon="🥛", items=["카페라떼", "카푸치노", "바닐라라떼", "카라멜마키아토", "말차라떼"]),
    AllergyInfo(name="글루텐", icon="🌾", items=["치즈케이크"]),
    AllergyInfo(name="견과류", icon="🥜", items=["치즈케이크"]),
    AllergyInfo(name="계란",   icon="🥚", items=["치즈케이크"]),
    AllergyInfo(name="대두",   icon="🌱", items=["말차라떼"]),
    AllergyInfo(name="과일류", icon="🍓", items=["딸기스무디"]),
]

INITIAL_TABLE_STATUS: list[str] = [
    "empty", "occupied", "empty", "occupied",
]

SHOT_SURCHARGE = 500
LOWFAT_MILK_SURCHARGE = 300
