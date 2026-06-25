-- db/seed_dirty_data.sql
-- Creates tables with intentionally dirty data for testing.
-- Includes: duplicates, nulls, orphan FKs, outliers.

-- ─────────────────────────────────────────────
-- 1. CUSTOMERS TABLE
-- ─────────────────────────────────────────────
CREATE TABLE customers (
    id            INT PRIMARY KEY,
    full_name     NVARCHAR(100),
    email         NVARCHAR(100),
    phone         NVARCHAR(20),
    city          NVARCHAR(50),
    created_at    DATETIME2 DEFAULT GETDATE()
);

INSERT INTO customers VALUES
(1,  'Ahmed Hassan',    'ahmed@email.com',   '0501234567', 'Cairo',        GETDATE()),
(2,  'Sara Ali',        'sara@email.com',     '0507654321', 'Alexandria',   GETDATE()),
(3,  'Mohamed Khaled',  NULL,                 '0509876543', 'Cairo',        GETDATE()),  -- null email
(4,  'Fatma Omar',      'fatma@email.com',    NULL,         'Giza',         GETDATE()),  -- null phone
(5,  'Ahmed Hassan',    'ahmed@email.com',    '0501234567', 'Cairo',        GETDATE()),  -- exact duplicate of row 1
(6,  'Sara Ali',        'sara@email.com',     '0507654321', 'Alexandria',   GETDATE()),  -- exact duplicate of row 2
(7,  'Karim Samir',     NULL,                 NULL,         NULL,           GETDATE()),  -- multiple nulls
(8,  'Layla Mostafa',   'layla@email.com',    '0501111111', 'Cairo',        GETDATE()),
(9,  'Omar Fathy',      'omar@email.com',     '0502222222', 'Alexandria',   GETDATE()),
(10, 'Nour Ahmed',      NULL,                 NULL,         'Giza',         GETDATE()); -- multiple nulls

-- ─────────────────────────────────────────────
-- 2. ORDERS TABLE
-- ─────────────────────────────────────────────
CREATE TABLE orders (
    id              INT PRIMARY KEY,
    customer_id     INT,               -- FK to customers (some will be orphans)
    product_name    NVARCHAR(100),
    amount          DECIMAL(10,2),
    status          NVARCHAR(20),
    order_date      DATETIME2 DEFAULT GETDATE()
);

INSERT INTO orders VALUES
(1,  1,   'Laptop',      999.99,   'completed',  GETDATE()),
(2,  2,   'Phone',       499.99,   'completed',  GETDATE()),
(3,  3,   'Tablet',      299.99,   'pending',    GETDATE()),
(4,  99,  'Headphones',  149.99,   'completed',  GETDATE()),  -- orphan FK (customer 99 doesn't exist)
(5,  88,  'Keyboard',    79.99,    'completed',  GETDATE()),  -- orphan FK (customer 88 doesn't exist)
(6,  1,   'Laptop',      999.99,   'completed',  GETDATE()),  -- duplicate of row 1
(7,  NULL,'Monitor',     399.99,   'pending',    GETDATE()),  -- null customer_id
(8,  4,   'Mouse',       29.99,    'completed',  GETDATE()),
(9,  5,   'Desk',        9999999,  'completed',  GETDATE()),  -- outlier amount
(10, 6,   'Chair',       NULL,     'pending',    GETDATE()); -- null amount

-- ─────────────────────────────────────────────
-- 3. PRODUCTS TABLE
-- ─────────────────────────────────────────────
CREATE TABLE products (
    id            INT PRIMARY KEY,
    name          NVARCHAR(100),
    category      NVARCHAR(50),
    price         DECIMAL(10,2),
    stock         INT,
    supplier_id   INT            -- FK to suppliers (orphans incoming)
);

INSERT INTO products VALUES
(1,  'Laptop Pro',     'Electronics', 999.99,  50,   1),
(2,  'Smart Phone',    'Electronics', 499.99,  120,  1),
(3,  'Wireless Mouse', 'Accessories', 29.99,   200,  2),
(4,  'Mechanical Keyboard', NULL,     79.99,   150,  NULL),  -- null category, null supplier
(5,  'USB Hub',        'Accessories', NULL,    75,   2),     -- null price
(6,  NULL,             'Electronics', 199.99,  30,   99),    -- null name, orphan supplier
(7,  'Monitor 4K',     'Electronics', 599.99,  25,   1),
(8,  'Laptop Pro',     'Electronics', 999.99,  50,   1),     -- duplicate of row 1
(9,  'Webcam HD',      'Accessories', 89.99,   NULL, 2),     -- null stock
(10, 'Smart Phone',    'Electronics', 499.99,  120,  1);     -- duplicate of row 2

-- ─────────────────────────────────────────────
-- 4. EMPLOYEES TABLE
-- ─────────────────────────────────────────────
CREATE TABLE employees (
    id            INT PRIMARY KEY,
    full_name     NVARCHAR(100),
    email         NVARCHAR(100),
    department    NVARCHAR(50),
    salary        DECIMAL(10,2),
    manager_id    INT            -- self-referencing FK
);

INSERT INTO employees VALUES
(1,  'Ali Mohamed',     'ali@company.com',    'Engineering',  85000,      NULL),      -- top manager
(2,  'Hana Samir',      'hana@company.com',   'Engineering',  72000,      1),
(3,  'Tarek Nasser',    NULL,                 'Marketing',    65000,      1),         -- null email
(4,  'Dina Khalil',     'dina@company.com',   NULL,           58000,      2),         -- null department
(5,  'Youssef Adel',    'youssef@company.com','Engineering',  9999999.99,  1),         -- outlier salary         -- outlier salary
(6,  'Mona Hassan',     'mona@company.com',   'Marketing',    61000,      99),        -- orphan manager_id
(7,  'Khaled Farouk',   NULL,                 NULL,           NULL,       1),         -- multiple nulls
(8,  'Ali Mohamed',     'ali@company.com',    'Engineering',  85000,      NULL),      -- duplicate of row 1
(9,  'Rania Mostafa',   'rania@company.com',  'HR',           54000,      3),
(10, 'Sameh Gamal',     'sameh@company.com',  'HR',           56000,      3);