CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    contact TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    address TEXT DEFAULT '',
    remark TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parts (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    spec TEXT DEFAULT '',
    color TEXT DEFAULT '',
    unit TEXT NOT NULL DEFAULT 'pcs',
    standard_qty INTEGER NOT NULL DEFAULT 0,
    count_method TEXT NOT NULL DEFAULT 'count',
    unit_weight DOUBLE PRECISION,
    box_capacity INTEGER,
    remark TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    customer_id BIGINT REFERENCES customers(id),
    remark TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_parts (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id),
    part_id BIGINT NOT NULL REFERENCES parts(id),
    ratio_qty DOUBLE PRECISION NOT NULL DEFAULT 1,
    remark TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product_id, part_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    order_no TEXT NOT NULL UNIQUE,
    customer TEXT NOT NULL DEFAULT '楼上客户',
    customer_id BIGINT REFERENCES customers(id),
    total_qty INTEGER NOT NULL DEFAULT 0,
    due_date TEXT DEFAULT '',
    remark TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_items (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    product_id BIGINT REFERENCES products(id),
    part_id BIGINT REFERENCES parts(id),
    qty INTEGER NOT NULL,
    shipped_qty INTEGER NOT NULL DEFAULT 0,
    remark TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS warehouse_areas (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    remark TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO warehouse_areas (code, name, remark)
VALUES ('A', '默认库区', '系统默认库区')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO system_settings (key, value) VALUES ('company_name', '深圳市宝恒源塑胶五金精密有限公司') ON CONFLICT (key) DO NOTHING;
INSERT INTO system_settings (key, value) VALUES ('server_host', '0.0.0.0') ON CONFLICT (key) DO NOTHING;
INSERT INTO system_settings (key, value) VALUES ('server_port', '5000') ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS boxes (
    id BIGSERIAL PRIMARY KEY,
    box_no TEXT NOT NULL UNIQUE,
    order_id BIGINT REFERENCES orders(id),
    order_item_id BIGINT REFERENCES order_items(id),
    product_id BIGINT REFERENCES products(id),
    part_id BIGINT NOT NULL REFERENCES parts(id),
    qty INTEGER NOT NULL,
    warehouse_area_id BIGINT REFERENCES warehouse_areas(id),
    status TEXT NOT NULL DEFAULT 'packed',
    printed INTEGER NOT NULL DEFAULT 0,
    printed_at TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stocked_at TEXT DEFAULT '',
    shipped_at TEXT DEFAULT '',
    returned_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS defects (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT REFERENCES products(id),
    part_id BIGINT REFERENCES parts(id),
    order_id BIGINT REFERENCES orders(id),
    qty INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS stock_moves (
    id BIGSERIAL PRIMARY KEY,
    move_type TEXT NOT NULL,
    box_no TEXT DEFAULT '',
    order_id BIGINT REFERENCES orders(id),
    order_item_id BIGINT REFERENCES order_items(id),
    product_id BIGINT REFERENCES products(id),
    part_id BIGINT REFERENCES parts(id),
    warehouse_area_id BIGINT REFERENCES warehouse_areas(id),
    qty INTEGER NOT NULL,
    note TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shipments (
    id BIGSERIAL PRIMARY KEY,
    shipment_no TEXT NOT NULL UNIQUE,
    customer_id BIGINT REFERENCES customers(id),
    status TEXT NOT NULL DEFAULT 'confirmed',
    remark TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shipment_items (
    id BIGSERIAL PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES shipments(id),
    box_id BIGINT NOT NULL REFERENCES boxes(id),
    box_no TEXT NOT NULL,
    order_id BIGINT REFERENCES orders(id),
    order_item_id BIGINT REFERENCES order_items(id),
    product_id BIGINT REFERENCES products(id),
    part_id BIGINT NOT NULL REFERENCES parts(id),
    qty INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
