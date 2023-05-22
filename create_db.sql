-- Example for creating a database
CREATE DATABASE IF NOT EXISTS mobile;
GRANT ALL PRIVILEGES ON mobile.* TO 'mobile'@'localhost' IDENTIFIED BY 'mobile';
FLUSH PRIVILEGES;
