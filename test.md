
테이크아웃 식사 주문

```
curl -i -X POST http://localhost:8000/api/orders \
    -H "Content-Type: application/json" \
    -d '{
        "channel": "kiosk",
        "receive_type": "take_out",
        "payment": "card",
        "items": [
            { "menu_id": 1, "qty": 2 }  
        ]
    }'
```

테이블 식사 주문

```
curl -i -X POST http://localhost:8000/api/orders \
    -H "Content-Type: application/json" \
    -d '{
        "channel": "kiosk",
        "receive_type": "dine_in",
        "payment": "card",
        "table_no": 1,
        "items": [
            { "menu_id": 2, "qty": 1 }
        ]
    }'
```