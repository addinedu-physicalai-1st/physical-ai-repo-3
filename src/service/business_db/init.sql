CREATE DATABASE IF NOT EXISTS business;

USE business;

CREATE TABLE IF NOT EXISTS service_metadata (
    id INT AUTO_INCREMENT PRIMARY KEY,
    service_name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO service_metadata (service_name, description)
SELECT 'business_db', 'Initial MySQL scaffold for business data'
WHERE NOT EXISTS (
    SELECT 1 FROM service_metadata WHERE service_name = 'business_db'
);
