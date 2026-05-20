def test_post_table_assignment_returns_success(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in", "table_id": 2},
    )

    assert r.status_code == 200
    assert r.json() == {"success": True}


def test_post_take_out_table_assignment_ignores_table_id(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "take_out", "table_id": 2},
    )

    assert r.status_code == 200


def test_post_dine_in_table_assignment_requires_table_id(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in"},
    )

    assert r.status_code == 400


def test_post_dine_in_table_assignment_rejects_zero_table_id(client):
    r = client.post(
        "/api/table-assignments",
        json={"order_id": 1001, "receive_type": "dine_in", "table_id": 0},
    )

    assert r.status_code == 400
