def test_get_menu_returns_8_items(client):
    r = client.get("/api/menu")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 8
    first = items[0]
    assert first["id"] == 1
    assert first["name"] == "아메리카노"
    assert first["price"] == 3500


def test_get_allergy_returns_6_categories(client):
    r = client.get("/api/allergy")
    assert r.status_code == 200
    cats = r.json()
    assert len(cats) == 6
    names = [c["name"] for c in cats]
    assert "유제품" in names
