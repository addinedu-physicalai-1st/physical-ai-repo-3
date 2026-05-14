def test_get_tables_returns_4_with_initial_seed(client):
    r = client.get("/api/tables")
    assert r.status_code == 200
    tables = r.json()
    assert len(tables) == 4
    # IDs are 1..4
    assert [t["id"] for t in tables] == [1, 2, 3, 4]
    # Seed: empty, occupied, empty, occupied
    assert [t["status"] for t in tables] == ["empty", "occupied", "empty", "occupied"]
