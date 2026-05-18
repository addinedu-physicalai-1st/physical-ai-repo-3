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
SELECT 'business_db', 'Initial MySQL scaffold for business data'
WHERE NOT EXISTS (
    SELECT 1 FROM service_metadata WHERE service_name = 'business_db'
);

CREATE TABLE IF NOT EXISTS menu_items (
    id INT PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    emoji VARCHAR(16) NOT NULL,
    price INT NOT NULL,
    hot BOOLEAN NOT NULL,
    shot BOOLEAN NOT NULL,
    ice BOOLEAN NOT NULL,
    milk BOOLEAN NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS allergy_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE,
    icon VARCHAR(16) NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS menu_item_allergies (
    menu_item_id INT NOT NULL,
    allergy_category_id INT NOT NULL,
    PRIMARY KEY (menu_item_id, allergy_category_id),
    CONSTRAINT fk_menu_item_allergies_menu
        FOREIGN KEY (menu_item_id) REFERENCES menu_items(id),
    CONSTRAINT fk_menu_item_allergies_allergy
        FOREIGN KEY (allergy_category_id) REFERENCES allergy_categories(id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS option_surcharges (
    option_key VARCHAR(64) PRIMARY KEY,
    price INT NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO menu_items (id, name, emoji, price, hot, shot, ice, milk) VALUES
    (1, '아메리카노', '☕', 3500, TRUE, TRUE, TRUE, FALSE),
    (2, '카페라떼', '☕', 4500, TRUE, TRUE, TRUE, TRUE),
    (3, '카푸치노', '🫧', 4500, TRUE, TRUE, FALSE, TRUE),
    (4, '바닐라라떼', '🌼', 5000, TRUE, TRUE, TRUE, TRUE),
    (5, '카라멜마키아토', '🍮', 5500, TRUE, TRUE, TRUE, TRUE),
    (6, '말차라떼', '🍵', 5500, TRUE, FALSE, TRUE, TRUE),
    (7, '딸기스무디', '🍓', 6000, FALSE, FALSE, TRUE, FALSE),
    (8, '치즈케이크', '🍰', 7000, FALSE, FALSE, FALSE, FALSE)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    emoji = VALUES(emoji),
    price = VALUES(price),
    hot = VALUES(hot),
    shot = VALUES(shot),
    ice = VALUES(ice),
    milk = VALUES(milk);

INSERT INTO allergy_categories (name, icon) VALUES
    ('유제품', '🥛'),
    ('글루텐', '🌾'),
    ('견과류', '🥜'),
    ('계란', '🥚'),
    ('대두', '🌱'),
    ('과일류', '🍓')
ON DUPLICATE KEY UPDATE icon = VALUES(icon);

INSERT IGNORE INTO menu_item_allergies (menu_item_id, allergy_category_id)
SELECT mi.id, ac.id
FROM menu_items mi
JOIN allergy_categories ac
WHERE (ac.name = '유제품' AND mi.name IN ('카페라떼', '카푸치노', '바닐라라떼', '카라멜마키아토', '말차라떼'))
   OR (ac.name = '글루텐' AND mi.name = '치즈케이크')
   OR (ac.name = '견과류' AND mi.name = '치즈케이크')
   OR (ac.name = '계란' AND mi.name = '치즈케이크')
   OR (ac.name = '대두' AND mi.name = '말차라떼')
   OR (ac.name = '과일류' AND mi.name = '딸기스무디');

INSERT INTO option_surcharges (option_key, price) VALUES
    ('shot:추가', 500),
    ('milk:저지방', 300)
ON DUPLICATE KEY UPDATE price = VALUES(price);
