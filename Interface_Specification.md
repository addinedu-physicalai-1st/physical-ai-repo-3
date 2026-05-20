# Interface Specification

## moca_service <-> web_service TCP

### Common MOCA frame

- frame header
    - purpose: wrap catalog, order, and table payloads
    - sender: web_service or moca_service
    - receiver: moca_service or web_service
    - protocol: tcp
    - payload:
        - cmd_type (1 byte)
            - menu: 0x20
            - allergy: 0x21
            - order: 0x22
            - table: 0x23
        - method (1 byte)
            - get: 0x01
            - set: 0x02
        - sequence (1 byte)
        - payload_size (4 byte, unsigned int, big-endian)
        - payload (payload_size byte)

### Common error payload

- error response
    - purpose: return a failed MOCA request result
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - status (1 byte)
            - error: 0x01
        - error_code (1 byte)
            - catalog_unavailable: 0x01
            - order_rejected: 0x02
            - table_unavailable: 0x03
            - order_not_found: 0x04
            - table_assignment_rejected: 0x05
        - message_size (2 byte, unsigned short, big-endian)
        - message (message_size byte, UTF-8)

### Catalog - Menu and Option

- menu option get request
    - purpose: request menu and option catalog
    - sender: web_service
    - receiver: moca_service
    - protocol: tcp
    - payload:
        - empty

- menu option get response
    - purpose: return menu and option catalog
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - status (1 byte)
            - ok: 0x00
        - menu_count (2 byte, unsigned short, big-endian)
        - repeat menu_count
            - product_id (2 byte, unsigned short, big-endian)
            - price (4 byte, unsigned int, big-endian)
            - name (256 byte, UTF-8, null-padded)
            - image (1020 byte, UTF-8, null-padded)
            - option_count (2 byte, unsigned short, big-endian)
            - repeat option_count
                - option_group (256 byte, UTF-8, null-padded)
                - option_name (256 byte, UTF-8, null-padded)
                - price (4 byte, unsigned int, big-endian)
                - is_default (1 byte)
                    - false: 0x00
                    - true: 0x01

- catalog option rule
    - purpose: define menu option selection rule
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - same option_group values belong to one option group
        - each option_group requires exactly one selected option
        - each option_group must have one option with is_default 0x01
        - price is the additional price for selecting that option

### Catalog - Allergy

- allergy get request
    - purpose: request allergy catalog
    - sender: web_service
    - receiver: moca_service
    - protocol: tcp
    - payload:
        - empty

- allergy get response
    - purpose: return allergy catalog
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - status (1 byte)
            - ok: 0x00
        - allergy_count (2 byte, unsigned short, big-endian)
        - repeat allergy_count
            - name (256 byte, UTF-8, null-padded)
            - icon (64 byte, UTF-8, null-padded)
            - item_count (2 byte, unsigned short, big-endian)
            - repeat item_count
                - item_name (256 byte, UTF-8, null-padded)

### Order

- order create request
    - purpose: create order
    - sender: web_service
    - receiver: moca_service
    - protocol: tcp
    - payload:
        - item_count (1 byte)
        - repeat item_count
            - product_id (2 byte, unsigned short, big-endian)
            - quantity (1 byte)

- order create response
    - purpose: return created order id
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - status (1 byte)
            - ok: 0x00
        - order_id (4 byte, unsigned int, big-endian)

### Table

- table get request
    - purpose: request table status
    - sender: web_service
    - receiver: moca_service
    - protocol: tcp
    - payload:
        - empty

- table get response
    - purpose: return table status
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - status (1 byte)
            - ok: 0x00
        - table_count (2 byte, unsigned short, big-endian)
        - repeat table_count
            - table_number (2 byte, unsigned short, big-endian)
            - table_status (1 byte)
                - empty: 0x00
                - occupied: 0x01

- table assignment request
    - purpose: assign table or take-out receive type to an order
    - sender: web_service
    - receiver: moca_service
    - protocol: tcp
    - payload:
        - order_id (4 byte, unsigned int, big-endian)
        - receive_type (1 byte)
            - take_out: 0x00
            - dine_in: 0x01
        - table_number (2 byte, unsigned short, big-endian)
            - 0 when receive_type is take_out

- table assignment response
    - purpose: return table assignment result
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - status (1 byte)
            - ok: 0x00

### Health and Status

- status notification
    - purpose: notify health/status probe result
    - sender: moca_service
    - receiver: web_service
    - protocol: tcp
    - payload:
        - stx (1 byte)
            - 0x02
        - cmd (1 byte)
            - status: 0x10
        - sequence (1 byte)
        - etx (1 byte)
            - 0x03
