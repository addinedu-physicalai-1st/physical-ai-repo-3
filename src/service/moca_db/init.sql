SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS business
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE business;

ALTER DATABASE business
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS service_metadata (
    id INT AUTO_INCREMENT PRIMARY KEY,
    service_name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO service_metadata (service_name, description)
SELECT 'moca_db', 'Initial MySQL scaffold for MOCA product catalog'
WHERE NOT EXISTS (
    SELECT 1 FROM service_metadata WHERE service_name = 'moca_db'
);

CREATE TABLE IF NOT EXISTS product (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NOT NULL,
    image_url VARCHAR(255) NOT NULL,
    price INT NOT NULL,
    product_type ENUM('DRINK', 'FOOD', 'SNACK') NOT NULL,
    menu_status ENUM('ON_SALE', 'SOLD_OUT', 'PAUSED') NOT NULL DEFAULT 'ON_SALE',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS product_option_group (
    product_option_group_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    name VARCHAR(64) NOT NULL,
    options JSON NOT NULL,
    required BOOLEAN NOT NULL DEFAULT FALSE,
    max_select_count INT NOT NULL DEFAULT 1,
    CONSTRAINT fk_product_option_group_product
        FOREIGN KEY (product_id) REFERENCES product(product_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_product_option_group_max_select_count
        CHECK (max_select_count > 0),
    CONSTRAINT chk_product_option_group_options_json
        CHECK (JSON_VALID(options))
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS allergy_category (
    allergy_category_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    icon VARCHAR(16) NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS product_allergy (
    product_id INT NOT NULL,
    allergy_category_id INT NOT NULL,
    PRIMARY KEY (product_id, allergy_category_id),
    CONSTRAINT fk_product_allergy_product
        FOREIGN KEY (product_id) REFERENCES product(product_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_product_allergy_category
        FOREIGN KEY (allergy_category_id) REFERENCES allergy_category(allergy_category_id)
        ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS map (
    map_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    width DECIMAL(10, 3) NOT NULL,
    height DECIMAL(10, 3) NOT NULL,
    address DECIMAL(10, 3) NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS store_table (
    table_id INT AUTO_INCREMENT PRIMARY KEY,
    map_id INT NOT NULL,
    table_number VARCHAR(32) NOT NULL,
    pos_x DECIMAL(10, 3) NOT NULL,
    pos_y DECIMAL(10, 3) NOT NULL,
    CONSTRAINT uq_store_table_map_table_number
        UNIQUE (map_id, table_number),
    CONSTRAINT fk_store_table_map
        FOREIGN KEY (map_id) REFERENCES map(map_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workspace (
    workspace_id INT AUTO_INCREMENT PRIMARY KEY,
    map_id INT NOT NULL,
    name VARCHAR(64) NOT NULL,
    CONSTRAINT fk_workspace_map
        FOREIGN KEY (map_id) REFERENCES map(map_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO map (map_id, name, width, height, address) VALUES
    (1, 'main', 0.000, 0.000, 0.000)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    width = VALUES(width),
    height = VALUES(height),
    address = VALUES(address);

INSERT INTO store_table (table_id, map_id, table_number, pos_x, pos_y) VALUES
    (1, 1, '1', 0.000, 0.000),
    (2, 1, '2', 0.000, 0.000),
    (3, 1, '3', 0.000, 0.000),
    (4, 1, '4', 0.000, 0.000)
ON DUPLICATE KEY UPDATE
    table_id = VALUES(table_id),
    map_id = VALUES(map_id),
    table_number = VALUES(table_number),
    pos_x = VALUES(pos_x),
    pos_y = VALUES(pos_y);

INSERT INTO workspace (workspace_id, map_id, name) VALUES
    (1, 1, 'main')
ON DUPLICATE KEY UPDATE
    map_id = VALUES(map_id),
    name = VALUES(name);

CREATE TABLE IF NOT EXISTS orders (
    order_id INT AUTO_INCREMENT PRIMARY KEY,
    order_source ENUM('COUNTER', 'TABLE') NOT NULL,
    receive_type ENUM('PENDING', 'DINE_IN', 'TAKE_OUT') NOT NULL DEFAULT 'PENDING',
    table_id INT NULL,
    order_status ENUM('PENDING', 'ACCEPTED', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELED') NOT NULL DEFAULT 'PENDING',
    payment_status ENUM('PENDING', 'PAID', 'CANCELED', 'REFUNDED') NOT NULL DEFAULT 'PENDING',
    total_price INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_store_table
        FOREIGN KEY (table_id) REFERENCES store_table(table_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,
    CONSTRAINT chk_orders_total_price
        CHECK (total_price >= 0)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_item (
    order_item_id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    selected_options JSON NOT NULL,
    quantity INT NOT NULL,
    unit_price INT NOT NULL,
    CONSTRAINT fk_order_item_order
        FOREIGN KEY (order_id) REFERENCES orders(order_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_order_item_product
        FOREIGN KEY (product_id) REFERENCES product(product_id)
        ON DELETE RESTRICT,
    CONSTRAINT chk_order_item_selected_options_json
        CHECK (JSON_VALID(selected_options)),
    CONSTRAINT chk_order_item_quantity
        CHECK (quantity > 0),
    CONSTRAINT chk_order_item_unit_price
        CHECK (unit_price >= 0)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO product (
    product_id,
    name,
    description,
    image_url,
    price,
    product_type,
    menu_status
) VALUES
    (1, '아메리카노', '진한 에스프레소에 물을 더한 기본 커피', '☕', 3500, 'DRINK', 'ON_SALE'),
    (2, '카페라떼', '에스프레소에 우유를 더한 부드러운 커피', '☕', 4500, 'DRINK', 'ON_SALE'),
    (3, '카푸치노', '풍성한 우유 거품을 올린 커피', '🫧', 4500, 'DRINK', 'ON_SALE'),
    (4, '바닐라라떼', '바닐라 시럽을 더한 달콤한 라떼', '🌼', 5000, 'DRINK', 'ON_SALE'),
    (5, '카라멜마키아토', '카라멜 향을 더한 달콤한 커피', '🍮', 5500, 'DRINK', 'ON_SALE'),
    (6, '말차라떼', '진한 말차와 우유가 어우러진 라떼', '🍵', 5500, 'DRINK', 'ON_SALE'),
    (7, '딸기스무디', '딸기 풍미의 시원한 스무디', '🍓', 6000, 'DRINK', 'ON_SALE'),
    (8, '치즈케이크', '진한 치즈 풍미의 디저트 케이크', '🍰', 7000, 'FOOD', 'ON_SALE')
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    description = VALUES(description),
    image_url = VALUES(image_url),
    price = VALUES(price),
    product_type = VALUES(product_type),
    menu_status = VALUES(menu_status);

INSERT INTO product_option_group (
    product_option_group_id,
    product_id,
    name,
    options,
    required,
    max_select_count
) VALUES
    (1, 1, '온도', JSON_ARRAY('HOT', 'ICE'), TRUE, 1),
    (2, 1, '에스프레소 샷', JSON_ARRAY('기본', JSON_OBJECT('name', '추가', 'price', 500)), FALSE, 1),
    (3, 2, '온도', JSON_ARRAY('HOT', 'ICE'), TRUE, 1),
    (4, 2, '에스프레소 샷', JSON_ARRAY('기본', JSON_OBJECT('name', '추가', 'price', 500)), FALSE, 1),
    (5, 2, '우유', JSON_ARRAY('일반', JSON_OBJECT('name', '저지방', 'price', 300)), FALSE, 1),
    (6, 3, '온도', JSON_ARRAY('HOT'), TRUE, 1),
    (7, 3, '에스프레소 샷', JSON_ARRAY('기본', JSON_OBJECT('name', '추가', 'price', 500)), FALSE, 1),
    (8, 3, '우유', JSON_ARRAY('일반', JSON_OBJECT('name', '저지방', 'price', 300)), FALSE, 1),
    (9, 4, '온도', JSON_ARRAY('HOT', 'ICE'), TRUE, 1),
    (10, 4, '에스프레소 샷', JSON_ARRAY('기본', JSON_OBJECT('name', '추가', 'price', 500)), FALSE, 1),
    (11, 4, '우유', JSON_ARRAY('일반', JSON_OBJECT('name', '저지방', 'price', 300)), FALSE, 1),
    (12, 5, '온도', JSON_ARRAY('HOT', 'ICE'), TRUE, 1),
    (13, 5, '에스프레소 샷', JSON_ARRAY('기본', JSON_OBJECT('name', '추가', 'price', 500)), FALSE, 1),
    (14, 5, '우유', JSON_ARRAY('일반', JSON_OBJECT('name', '저지방', 'price', 300)), FALSE, 1),
    (15, 6, '온도', JSON_ARRAY('HOT', 'ICE'), TRUE, 1),
    (16, 6, '우유', JSON_ARRAY('일반', JSON_OBJECT('name', '저지방', 'price', 300)), FALSE, 1),
    (17, 7, '온도', JSON_ARRAY('ICE'), TRUE, 1)
ON DUPLICATE KEY UPDATE
    product_id = VALUES(product_id),
    name = VALUES(name),
    options = VALUES(options),
    required = VALUES(required),
    max_select_count = VALUES(max_select_count);

INSERT INTO allergy_category (allergy_category_id, name, icon) VALUES
    (1, '유제품', '🥛'),
    (2, '글루텐', '🌾'),
    (3, '견과류', '🥜'),
    (4, '계란', '🥚'),
    (5, '대두', '🌱'),
    (6, '과일류', '🍓')
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    icon = VALUES(icon);

INSERT IGNORE INTO product_allergy (product_id, allergy_category_id)
SELECT p.product_id, ac.allergy_category_id
FROM product p
JOIN allergy_category ac
WHERE (ac.name = '유제품' AND p.name IN ('카페라떼', '카푸치노', '바닐라라떼', '카라멜마키아토', '말차라떼'))
   OR (ac.name = '글루텐' AND p.name = '치즈케이크')
   OR (ac.name = '견과류' AND p.name = '치즈케이크')
   OR (ac.name = '계란' AND p.name = '치즈케이크')
   OR (ac.name = '대두' AND p.name = '말차라떼')
   OR (ac.name = '과일류' AND p.name = '딸기스무디');
