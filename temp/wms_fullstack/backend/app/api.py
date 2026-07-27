import csv
import io
from datetime import datetime
from functools import wraps

from flask import Blueprint, Response, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, get_db, query_all, query_one

bp = Blueprint('api', __name__)


def ok(data=None, status=200, **extra):
    payload = {'ok': True}
    if data is not None:
        payload['data'] = data
    payload.update(extra)
    return jsonify(payload), status


def fail(message, status=400, code='bad_request'):
    return jsonify({'ok': False, 'error': {'code': code, 'message': message}}), status


def current_user():
    username = request.headers.get('X-WMS-User', '').strip()
    if not username:
        return None
    return query_one('SELECT * FROM users WHERE username=? AND active=1', (username,))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return fail('请先登录', 401, 'unauthorized')
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return fail('请先登录', 401, 'unauthorized')
        if user['role'] != 'admin':
            return fail('需要管理员权限', 403, 'forbidden')
        return fn(*args, **kwargs)
    return wrapper


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def require_json():
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError('请求体必须是 JSON')
    return data


def positive_int(value, field):
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field} 必须是正整数')
    if value <= 0:
        raise ValueError(f'{field} 必须是正整数')
    return value


def optional_positive_int(value, field):
    if value in (None, ''):
        return None
    return positive_int(value, field)


def number_value(value, field, default=1):
    if value in (None, ''):
        return default
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field} 必须是数字')
    if value <= 0:
        raise ValueError(f'{field} 必须大于 0')
    return value


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def like_arg(value):
    return f"%{str(value).strip()}%"


def query_filters(mapping):
    clauses = []
    args = []
    for param, expression in mapping:
        value = request.args.get(param, '').strip()
        if value:
            clauses.append(expression)
            args.append(like_arg(value))
    return clauses, args


def setting_map():
    rows = rows_to_dicts(query_all('SELECT key, value FROM system_settings ORDER BY key'))
    return {row['key']: row['value'] for row in rows}


def upsert_setting(key, value):
    if query_one('SELECT key FROM system_settings WHERE key=?', (key,)):
        execute('UPDATE system_settings SET value=?, updated_at=CURRENT_TIMESTAMP WHERE key=?', (str(value), key))
    else:
        execute('INSERT INTO system_settings (key, value) VALUES (?, ?)', (key, str(value)))


def save_product_parts(product_id, components):
    execute('DELETE FROM product_parts WHERE product_id=?', (product_id,))
    for item in components or []:
        part_id = positive_int(item.get('part_id'), '部件')
        ratio_qty = number_value(item.get('ratio_qty', item.get('qty', 1)), '比例数量')
        remark = str(item.get('remark', '')).strip()
        if not query_one('SELECT id FROM parts WHERE id=? AND active=1', (part_id,)):
            raise ValueError('部件不存在')
        execute(
            'INSERT INTO product_parts (product_id, part_id, ratio_qty, remark) VALUES (?, ?, ?, ?)',
            (product_id, part_id, ratio_qty, remark),
        )


def product_with_parts(product_id):
    product = row_to_dict(query_one('''
        SELECT p.*, c.name AS customer_name, c.code AS customer_code
        FROM products p LEFT JOIN customers c ON c.id=p.customer_id
        WHERE p.id=?
    ''', (product_id,)))
    if not product:
        return None
    product['components'] = rows_to_dicts(query_all('''
        SELECT pp.id, pp.part_id, pp.ratio_qty, pp.remark,
               pt.code AS part_code, pt.name AS part_name, pt.spec, pt.color, pt.unit, pt.standard_qty, pt.count_method
        FROM product_parts pp JOIN parts pt ON pt.id=pp.part_id
        WHERE pp.product_id=?
        ORDER BY pt.code
    ''', (product_id,)))
    return product


def order_with_items(order_id):
    order = row_to_dict(query_one('''
        SELECT o.*, c.name AS customer_name, c.code AS customer_code
        FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
        WHERE o.id=?
    ''', (order_id,)))
    if not order:
        return None
    order['items'] = rows_to_dicts(query_all('''
        SELECT oi.*, p.code AS product_code, p.name AS product_name,
               pt.code AS part_code, pt.name AS part_name, pt.spec, pt.color, pt.unit,
               (oi.qty - oi.shipped_qty) AS open_qty
        FROM order_items oi
        LEFT JOIN products p ON p.id=oi.product_id
        LEFT JOIN parts pt ON pt.id=oi.part_id
        WHERE oi.order_id=?
        ORDER BY oi.id
    ''', (order_id,)))
    return order


def box_detail_by_no(box_no):
    return row_to_dict(query_one('''
        SELECT b.*, o.order_no, p.code AS product_code, p.name AS product_name,
               pt.code AS part_code, pt.name AS part_name, pt.spec, pt.color, pt.unit,
               wa.code AS area_code, wa.name AS area_name
        FROM boxes b
        LEFT JOIN orders o ON o.id=b.order_id
        LEFT JOIN products p ON p.id=b.product_id
        JOIN parts pt ON pt.id=b.part_id
        LEFT JOIN warehouse_areas wa ON wa.id=b.warehouse_area_id
        WHERE b.box_no=?
    ''', (box_no,)))


def ensure_default_admin():
    if query_one('SELECT id FROM users WHERE username=?', ('admin',)):
        return
    execute(
        'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
        ('admin', generate_password_hash('admin123'), 'admin'),
    )
    get_db().commit()


def public_user(user):
    data = row_to_dict(user)
    if data:
        data.pop('password_hash', None)
    return data


def next_box_no(part_id):
    part = query_one('SELECT code FROM parts WHERE id=?', (part_id,))
    part_code = part['code'] if part else str(part_id)
    prefix = f'{datetime.now().strftime("%Y%m%d")}-{part_code}'
    row = query_one('SELECT box_no FROM boxes WHERE box_no LIKE ? ORDER BY box_no DESC LIMIT 1', (f'{prefix}-%',))
    seq = int(row['box_no'].rsplit('-', 1)[-1]) + 1 if row else 1
    return f'{prefix}-{seq:03d}'


@bp.post('/login')
def login():
    try:
        ensure_default_admin()
        data = require_json()
        username = str(data.get('username', '')).strip()
        password = str(data.get('password', ''))
        user = query_one('SELECT * FROM users WHERE username=? AND active=1', (username,))
        if not user or not check_password_hash(user['password_hash'], password):
            return fail('用户名或密码错误', 401, 'invalid_credentials')
        return ok({'user': public_user(user)})
    except ValueError as exc:
        return fail(str(exc))


@bp.get('/me')
def me():
    ensure_default_admin()
    user = current_user()
    return ok({'user': public_user(user) if user else None})


@bp.get('/dashboard')
def dashboard():
    data = {
        'customers': query_one('SELECT COUNT(*) AS n FROM customers WHERE active=1')['n'],
        'parts': query_one('SELECT COUNT(*) AS n FROM parts WHERE active=1')['n'],
        'products': query_one('SELECT COUNT(*) AS n FROM products WHERE active=1')['n'],
        'orders': query_one('SELECT COUNT(*) AS n FROM orders')['n'],
        'packed_boxes': query_one("SELECT COUNT(*) AS n FROM boxes WHERE status='packed'")['n'],
        'in_stock_boxes': query_one("SELECT COUNT(*) AS n FROM boxes WHERE status='in_stock'")['n'],
        'shipped_boxes': query_one("SELECT COUNT(*) AS n FROM boxes WHERE status='shipped'")['n'],
        'returned_boxes': query_one("SELECT COUNT(*) AS n FROM boxes WHERE status='returned'")['n'],
        'stock_qty': query_one("SELECT COALESCE(SUM(qty),0) AS n FROM boxes WHERE status='in_stock'")['n'],
        'shipped_qty': query_one("SELECT COALESCE(SUM(qty),0) AS n FROM boxes WHERE status='shipped'")['n'],
        'returned_qty': query_one("SELECT COALESCE(SUM(qty),0) AS n FROM boxes WHERE status='returned'")['n'],
        'open_qty': query_one('SELECT COALESCE(SUM(qty - shipped_qty),0) AS n FROM order_items')['n'],
    }
    return ok(data)


@bp.route('/customers', methods=['GET', 'POST'])
def customers():
    if request.method == 'GET':
        clauses, args = query_filters([('q', '(code LIKE ? OR name LIKE ? OR contact LIKE ? OR phone LIKE ?)')])
        if args:
            args = args * 4
        sql = 'SELECT * FROM customers WHERE active=1'
        if clauses:
            sql += ' AND ' + ' AND '.join(clauses)
        sql += ' ORDER BY code'
        return ok(rows_to_dicts(query_all(sql, args)))
    try:
        data = require_json()
        code = str(data.get('code', '')).strip()
        name = str(data.get('name', '')).strip()
        if not code or not name:
            return fail('客户编码和名称不能为空')
        execute('''
            INSERT INTO customers (code, name, contact, phone, address, remark)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (code, name, data.get('contact', ''), data.get('phone', ''), data.get('address', ''), data.get('remark', '')))
        get_db().commit()
        return ok(row_to_dict(query_one('SELECT * FROM customers WHERE code=?', (code,))), 201)
    except ValueError as exc:
        return fail(str(exc))


@bp.route('/customers/<int:customer_id>', methods=['PUT', 'DELETE'])
@admin_required
def customer_detail(customer_id):
    if not query_one('SELECT id FROM customers WHERE id=? AND active=1', (customer_id,)):
        return fail('客户不存在', 404, 'customer_not_found')
    if request.method == 'DELETE':
        execute('UPDATE customers SET active=0 WHERE id=?', (customer_id,))
        get_db().commit()
        return ok({'deleted': True})
    data = require_json()
    code = str(data.get('code', '')).strip()
    name = str(data.get('name', '')).strip()
    if not code or not name:
        return fail('客户编码和名称不能为空')
    try:
        execute('''
            UPDATE customers SET code=?, name=?, contact=?, phone=?, address=?, remark=? WHERE id=?
        ''', (code, name, data.get('contact', ''), data.get('phone', ''), data.get('address', ''), data.get('remark', ''), customer_id))
        get_db().commit()
        return ok(row_to_dict(query_one('SELECT * FROM customers WHERE id=?', (customer_id,))))
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.route('/parts', methods=['GET', 'POST'])
def parts():
    if request.method == 'GET':
        clauses, args = query_filters([('q', '(code LIKE ? OR name LIKE ? OR spec LIKE ? OR color LIKE ?)')])
        if args:
            args = args * 4
        count_method = request.args.get('count_method', '').strip()
        sql = 'SELECT * FROM parts WHERE active=1'
        if clauses:
            sql += ' AND ' + ' AND '.join(clauses)
        if count_method:
            sql += ' AND count_method=?'
            args.append(count_method)
        sql += ' ORDER BY code'
        return ok(rows_to_dicts(query_all(sql, args)))
    try:
        data = require_json()
        code = str(data.get('code', '')).strip()
        name = str(data.get('name', '')).strip()
        if not code or not name:
            return fail('部件编码和名称不能为空')
        standard_qty = int(data.get('standard_qty', data.get('qty', 0)) or 0)
        if standard_qty < 0:
            return fail('部件数量不能小于 0')
        box_capacity = optional_positive_int(data.get('box_capacity'), '箱容量')
        unit_weight = data.get('unit_weight')
        unit_weight = None if unit_weight in (None, '') else float(unit_weight)
        execute('''
            INSERT INTO parts (code, name, spec, color, unit, standard_qty, count_method, unit_weight, box_capacity, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (code, name, data.get('spec', ''), data.get('color', ''), data.get('unit', 'pcs'), standard_qty,
              data.get('count_method', 'count'), unit_weight, box_capacity, data.get('remark', '')))
        get_db().commit()
        return ok(row_to_dict(query_one('SELECT * FROM parts WHERE code=?', (code,))), 201)
    except (ValueError, TypeError) as exc:
        return fail(str(exc))


@bp.route('/parts/<int:part_id>', methods=['PUT', 'DELETE'])
@admin_required
def part_detail(part_id):
    if not query_one('SELECT id FROM parts WHERE id=? AND active=1', (part_id,)):
        return fail('部件不存在', 404, 'part_not_found')
    if request.method == 'DELETE':
        execute('UPDATE parts SET active=0 WHERE id=?', (part_id,))
        get_db().commit()
        return ok({'deleted': True})
    data = require_json()
    code = str(data.get('code', '')).strip()
    name = str(data.get('name', '')).strip()
    if not code or not name:
        return fail('部件编码和名称不能为空')
    standard_qty = int(data.get('standard_qty', data.get('qty', 0)) or 0)
    if standard_qty < 0:
        return fail('部件数量不能小于 0')
    unit_weight = data.get('unit_weight')
    unit_weight = None if unit_weight in (None, '') else float(unit_weight)
    box_capacity = optional_positive_int(data.get('box_capacity'), '箱容量')
    execute('''
        UPDATE parts SET code=?, name=?, spec=?, color=?, unit=?, standard_qty=?, count_method=?, unit_weight=?, box_capacity=?, remark=? WHERE id=?
    ''', (code, name, data.get('spec', ''), data.get('color', ''), data.get('unit', 'PCS'), standard_qty,
          data.get('count_method', 'count'), unit_weight, box_capacity, data.get('remark', ''), part_id))
    get_db().commit()
    return ok(row_to_dict(query_one('SELECT * FROM parts WHERE id=?', (part_id,))))


@bp.route('/products', methods=['GET', 'POST'])
def products():
    if request.method == 'GET':
        clauses, args = query_filters([('q', '(p.code LIKE ? OR p.name LIKE ? OR c.name LIKE ?)')])
        if args:
            args = args * 3
        sql = '''
            SELECT p.*, c.name AS customer_name, c.code AS customer_code,
                   COUNT(pp.id) AS component_count
            FROM products p
            LEFT JOIN customers c ON c.id=p.customer_id
            LEFT JOIN product_parts pp ON pp.product_id=p.id
            WHERE p.active=1
        '''
        if clauses:
            sql += ' AND ' + ' AND '.join(clauses)
        sql += ' GROUP BY p.id, c.name, c.code ORDER BY p.code'
        rows = rows_to_dicts(query_all(sql, args))
        for row in rows:
            row['components'] = product_with_parts(row['id'])['components']
        return ok(rows)
    try:
        data = require_json()
        code = str(data.get('code', '')).strip()
        name = str(data.get('name', '')).strip()
        if not code or not name:
            return fail('产品编码和名称不能为空')
        execute('INSERT INTO products (code, name, customer_id, remark) VALUES (?, ?, ?, ?)',
                (code, name, None, data.get('remark', '')))
        product_id = query_one('SELECT id FROM products WHERE code=?', (code,))['id']
        components = data.get('components') if data.get('components') is not None else data.get('bom', [])
        save_product_parts(product_id, components)
        get_db().commit()
        return ok(product_with_parts(product_id), 201)
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.route('/products/<int:product_id>', methods=['PUT', 'DELETE'])
@admin_required
def product_detail(product_id):
    if not query_one('SELECT id FROM products WHERE id=? AND active=1', (product_id,)):
        return fail('产品不存在', 404, 'product_not_found')
    if request.method == 'DELETE':
        execute('UPDATE products SET active=0 WHERE id=?', (product_id,))
        get_db().commit()
        return ok({'deleted': True})
    data = require_json()
    code = str(data.get('code', '')).strip()
    name = str(data.get('name', '')).strip()
    if not code or not name:
        return fail('产品编码和名称不能为空')
    try:
        execute('UPDATE products SET code=?, name=?, customer_id=?, remark=? WHERE id=?',
                (code, name, None, data.get('remark', ''), product_id))
        components = data.get('components') if data.get('components') is not None else data.get('bom', [])
        save_product_parts(product_id, components)
        get_db().commit()
        return ok(product_with_parts(product_id))
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.get('/products/<int:product_id>/parts')
def product_parts(product_id):
    product = product_with_parts(product_id)
    if not product:
        return fail('产品不存在', 404, 'product_not_found')
    return ok(product['components'])


@bp.route('/orders', methods=['GET', 'POST'])
def orders():
    if request.method == 'GET':
        clauses, args = query_filters([('q', '(o.order_no LIKE ? OR o.customer LIKE ? OR c.name LIKE ? OR p.name LIKE ? OR pt.name LIKE ?)')])
        if args:
            args = args * 5
        sql = '''
            SELECT o.*, c.name AS customer_name, c.code AS customer_code,
                   COALESCE(SUM(oi.qty),0) AS item_qty,
                   COALESCE(SUM(oi.shipped_qty),0) AS shipped_qty,
                   COALESCE(SUM(oi.qty - oi.shipped_qty),0) AS open_qty,
                   COUNT(oi.id) AS item_count
            FROM orders o
            LEFT JOIN customers c ON c.id=o.customer_id
            LEFT JOIN order_items oi ON oi.order_id=o.id
            LEFT JOIN products p ON p.id=oi.product_id
            LEFT JOIN parts pt ON pt.id=oi.part_id
            WHERE 1=1
        '''
        if clauses:
            sql += ' AND ' + ' AND '.join(clauses)
        sql += ' GROUP BY o.id, c.name, c.code ORDER BY o.created_at DESC, o.id DESC'
        rows = rows_to_dicts(query_all(sql, args))
        for row in rows:
            row['items'] = order_with_items(row['id'])['items']
        return ok(rows)
    try:
        data = require_json()
        order_no = str(data.get('order_no', '')).strip()
        if not order_no:
            return fail('订单号不能为空')
        customer_id = optional_positive_int(data.get('customer_id'), '客户')
        customer_name = str(data.get('customer', '')).strip()
        if customer_id:
            customer = query_one('SELECT name FROM customers WHERE id=? AND active=1', (customer_id,))
            if not customer:
                return fail('客户不存在', 404, 'customer_not_found')
            customer_name = customer_name or customer['name']
        items = data.get('items') or []
        if not items and data.get('product_id'):
            items = [{'product_id': data.get('product_id'), 'qty': data.get('total_qty')}]
        if not items:
            return fail('订单明细不能为空')
        execute('INSERT INTO orders (order_no, customer, customer_id, total_qty, due_date, remark) VALUES (?, ?, ?, ?, ?, ?)',
                (order_no, customer_name or '楼上客户', customer_id, 0, data.get('due_date', ''), data.get('remark', '')))
        order_id = query_one('SELECT id FROM orders WHERE order_no=?', (order_no,))['id']
        total_qty = 0
        for item in items:
            qty = positive_int(item.get('qty'), '订单明细数量')
            product_id = optional_positive_int(item.get('product_id'), '产品')
            part_id = optional_positive_int(item.get('part_id'), '部件')
            if not product_id and not part_id:
                raise ValueError('订单明细必须选择产品或部件')
            if product_id and not query_one('SELECT id FROM products WHERE id=? AND active=1', (product_id,)):
                raise ValueError('产品不存在')
            if part_id and not query_one('SELECT id FROM parts WHERE id=? AND active=1', (part_id,)):
                raise ValueError('部件不存在')
            execute('INSERT INTO order_items (order_id, product_id, part_id, qty, remark) VALUES (?, ?, ?, ?, ?)',
                    (order_id, product_id, part_id, qty, item.get('remark', '')))
            total_qty += qty
        execute('UPDATE orders SET total_qty=? WHERE id=?', (total_qty, order_id))
        get_db().commit()
        return ok(order_with_items(order_id), 201)
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.route('/orders/<int:order_id>', methods=['PUT', 'DELETE'])
@admin_required
def order_detail(order_id):
    if not query_one('SELECT id FROM orders WHERE id=?', (order_id,)):
        return fail('订单不存在', 404, 'order_not_found')
    if request.method == 'DELETE':
        execute('DELETE FROM order_items WHERE order_id=?', (order_id,))
        execute('DELETE FROM orders WHERE id=?', (order_id,))
        get_db().commit()
        return ok({'deleted': True})
    data = require_json()
    order_no = str(data.get('order_no', '')).strip()
    if not order_no:
        return fail('订单号不能为空')
    customer_id = optional_positive_int(data.get('customer_id'), '客户')
    customer_name = str(data.get('customer', '')).strip()
    if customer_id:
        customer = query_one('SELECT name FROM customers WHERE id=? AND active=1', (customer_id,))
        if not customer:
            return fail('客户不存在', 404, 'customer_not_found')
        customer_name = customer_name or customer['name']
    items = data.get('items') or []
    if not items:
        return fail('订单明细不能为空')
    try:
        execute('UPDATE orders SET order_no=?, customer=?, customer_id=?, total_qty=?, due_date=?, remark=? WHERE id=?',
                (order_no, customer_name or '楼上客户', customer_id, 0, data.get('due_date', ''), data.get('remark', ''), order_id))
        execute('DELETE FROM order_items WHERE order_id=?', (order_id,))
        total_qty = 0
        for item in items:
            qty = positive_int(item.get('qty'), '订单明细数量')
            product_id = optional_positive_int(item.get('product_id'), '产品')
            part_id = optional_positive_int(item.get('part_id'), '部件')
            if not product_id and not part_id:
                raise ValueError('订单明细必须选择产品或部件')
            if product_id and not query_one('SELECT id FROM products WHERE id=? AND active=1', (product_id,)):
                raise ValueError('产品不存在')
            if part_id and not query_one('SELECT id FROM parts WHERE id=? AND active=1', (part_id,)):
                raise ValueError('部件不存在')
            shipped_qty = int(item.get('shipped_qty', 0) or 0)
            execute('INSERT INTO order_items (order_id, product_id, part_id, qty, shipped_qty, remark) VALUES (?, ?, ?, ?, ?, ?)',
                    (order_id, product_id, part_id, qty, shipped_qty, item.get('remark', '')))
            total_qty += qty
        execute('UPDATE orders SET total_qty=? WHERE id=?', (total_qty, order_id))
        get_db().commit()
        return ok(order_with_items(order_id))
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.get('/users')
@admin_required
def users():
    return ok(rows_to_dicts(query_all('SELECT id, username, role, active, created_at FROM users ORDER BY username')))


@bp.route('/users', methods=['POST'])
@admin_required
def create_user():
    data = require_json()
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', '')).strip()
    role = str(data.get('role', 'operator')).strip() or 'operator'
    if not username or not password:
        return fail('用户名和密码不能为空')
    if role not in ('admin', 'operator'):
        return fail('角色只能是 admin 或 operator')
    execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', (username, generate_password_hash(password), role))
    get_db().commit()
    return ok(row_to_dict(query_one('SELECT id, username, role, active, created_at FROM users WHERE username=?', (username,))), 201)


@bp.route('/users/<int:user_id>', methods=['PUT', 'DELETE'])
@admin_required
def user_detail(user_id):
    user = query_one('SELECT * FROM users WHERE id=?', (user_id,))
    if not user:
        return fail('用户不存在', 404, 'user_not_found')
    if request.method == 'DELETE':
        execute('UPDATE users SET active=0 WHERE id=?', (user_id,))
        get_db().commit()
        return ok({'deleted': True})
    data = require_json()
    role = str(data.get('role', user['role'])).strip() or user['role']
    active = 1 if data.get('active', user['active']) else 0
    if role not in ('admin', 'operator'):
        return fail('角色只能是 admin 或 operator')
    password = str(data.get('password', '')).strip()
    if password:
        execute('UPDATE users SET role=?, active=?, password_hash=? WHERE id=?', (role, active, generate_password_hash(password), user_id))
    else:
        execute('UPDATE users SET role=?, active=? WHERE id=?', (role, active, user_id))
    get_db().commit()
    return ok(row_to_dict(query_one('SELECT id, username, role, active, created_at FROM users WHERE id=?', (user_id,))))


@bp.route('/settings', methods=['GET', 'PUT'])
@admin_required
def settings():
    if request.method == 'GET':
        return ok(setting_map())
    data = require_json()
    for key in ('company_name', 'server_host', 'server_port'):
        if key in data:
            upsert_setting(key, data.get(key, ''))
    get_db().commit()
    return ok(setting_map())


@bp.get('/warehouse-areas')
def warehouse_areas():
    return ok(rows_to_dicts(query_all('SELECT * FROM warehouse_areas WHERE active=1 ORDER BY code')))


@bp.route('/warehouse-areas', methods=['POST'])
def create_warehouse_area():
    try:
        data = require_json()
        code = str(data.get('code', '')).strip()
        name = str(data.get('name', '')).strip()
        if not code or not name:
            return fail('库区编码和名称不能为空')
        execute('INSERT INTO warehouse_areas (code, name, remark) VALUES (?, ?, ?)', (code, name, data.get('remark', '')))
        get_db().commit()
        return ok(row_to_dict(query_one('SELECT * FROM warehouse_areas WHERE code=?', (code,))), 201)
    except ValueError as exc:
        return fail(str(exc))


@bp.route('/warehouse-areas/<int:area_id>', methods=['PUT', 'DELETE'])
@admin_required
def warehouse_area_detail(area_id):
    area = query_one('SELECT * FROM warehouse_areas WHERE id=? AND active=1', (area_id,))
    if not area:
        return fail('库区不存在', 404, 'warehouse_area_not_found')
    if request.method == 'DELETE':
        execute('UPDATE warehouse_areas SET active=0 WHERE id=?', (area_id,))
        get_db().commit()
        return ok({'deleted': True})
    data = require_json()
    code = str(data.get('code', area['code'])).strip()
    name = str(data.get('name', area['name'])).strip()
    if not code or not name:
        return fail('库区编码和名称不能为空')
    execute('UPDATE warehouse_areas SET code=?, name=?, remark=? WHERE id=?', (code, name, data.get('remark', area['remark']), area_id))
    get_db().commit()
    return ok(row_to_dict(query_one('SELECT * FROM warehouse_areas WHERE id=?', (area_id,))))


@bp.get('/boxes/recent')
def recent_boxes():
    return ok(rows_to_dicts(query_all('''
        SELECT b.*, p.code AS product_code, p.name AS product_name,
               pt.code AS part_code, pt.name AS part_name, pt.spec, pt.color, pt.unit,
               wa.code AS area_code, wa.name AS area_name
        FROM boxes b
        LEFT JOIN products p ON p.id=b.product_id
        JOIN parts pt ON pt.id=b.part_id
        LEFT JOIN warehouse_areas wa ON wa.id=b.warehouse_area_id
        ORDER BY b.created_at DESC, b.id DESC
        LIMIT 100
    ''')))


@bp.post('/produce')
def produce_box():
    try:
        data = require_json()
        part_id = optional_positive_int(data.get('part_id'), '部件')
        if not part_id:
            return fail('装箱必须选择部件')
        part = query_one('SELECT * FROM parts WHERE id=? AND active=1', (part_id,))
        if not part:
            return fail('部件不存在', 404, 'part_not_found')
        qty_value = data.get('qty')
        if part['count_method'] == 'weight' and qty_value in (None, ''):
            return fail('称重部件必须填写本箱数量')
        if qty_value in (None, ''):
            qty_value = part['box_capacity'] or 1
        qty = positive_int(qty_value, '装箱数量')
        box_count = positive_int(data.get('box_count', 1), '生成箱数')
        if box_count > 100:
            return fail('一次最多生成 100 箱')
        manual_box_no = str(data.get('box_no', '')).strip()
        if manual_box_no and box_count > 1:
            return fail('手工箱号一次只能生成 1 箱')
        box_no = manual_box_no or next_box_no(part_id)
        if query_one('SELECT id FROM boxes WHERE box_no=?', (box_no,)):
            return fail('箱号已存在', 409, 'box_exists')
        area_id = optional_positive_int(data.get('warehouse_area_id'), '库区')
        if area_id is None:
            default_area = query_one("SELECT id FROM warehouse_areas WHERE code='A'")
            area_id = default_area['id'] if default_area else None
        status = data.get('status') or 'packed'
        if status not in ('packed', 'in_stock'):
            status = 'packed'
        stocked_at = now_text() if status == 'in_stock' else ''
        user = current_user()
        created_by = user['username'] if user else str(data.get('created_by', '')).strip()
        created = []
        for _ in range(box_count):
            current_box_no = manual_box_no or next_box_no(part_id)
            if query_one('SELECT id FROM boxes WHERE box_no=?', (current_box_no,)):
                return fail(f'箱号已存在：{current_box_no}', 409, 'box_exists')
            execute('''
                INSERT INTO boxes (box_no, part_id, qty, warehouse_area_id, status, stocked_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (current_box_no, part_id, qty, area_id, status, stocked_at, created_by))
            execute('''
                INSERT INTO stock_moves (move_type, box_no, part_id, warehouse_area_id, qty, note)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ('produce' if status == 'packed' else 'stock_in', current_box_no, part_id, area_id, qty, data.get('note', '生产装箱')))
            created.append(current_box_no)
        get_db().commit()
        return ok({'boxes': [box_detail_by_no(no) for no in created], 'count': len(created)}, 201)
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.post('/stock-in')
def stock_in():
    try:
        data = require_json()
        box_no = str(data.get('box_no', '')).strip()
        area_id = optional_positive_int(data.get('warehouse_area_id'), '库区')
        row = query_one('SELECT * FROM boxes WHERE box_no=?', (box_no,))
        if not row:
            return fail('箱号不存在', 404, 'box_not_found')
        if row['status'] == 'shipped':
            return fail('已出货箱号不能入库', 409, 'already_shipped')
        if row['status'] == 'in_stock':
            return fail('箱号已在库存中', 409, 'already_in_stock')
        if area_id is None:
            area_id = row['warehouse_area_id']
        execute("UPDATE boxes SET status='in_stock', warehouse_area_id=?, stocked_at=? WHERE box_no=?", (area_id, now_text(), box_no))
        execute('''
            INSERT INTO stock_moves (move_type, box_no, order_id, order_item_id, product_id, part_id, warehouse_area_id, qty, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('stock_in', box_no, row['order_id'], row['order_item_id'], row['product_id'], row['part_id'], area_id, row['qty'], data.get('note', '箱号入库')))
        get_db().commit()
        return ok(box_detail_by_no(box_no))
    except ValueError as exc:
        return fail(str(exc))


@bp.get('/boxes')
def boxes():
    clauses, args = query_filters([('q', '(b.box_no LIKE ? OR o.order_no LIKE ? OR p.code LIKE ? OR p.name LIKE ? OR pt.code LIKE ? OR pt.name LIKE ?)')])
    if args:
        args = args * 6
    status = request.args.get('status', '').strip()
    printed = request.args.get('printed', '').strip()
    sql = '''
        SELECT b.*, o.order_no, p.code AS product_code, p.name AS product_name,
               pt.code AS part_code, pt.name AS part_name, pt.spec, pt.color, pt.unit,
               wa.code AS area_code, wa.name AS area_name
        FROM boxes b
        LEFT JOIN orders o ON o.id=b.order_id
        LEFT JOIN products p ON p.id=b.product_id
        JOIN parts pt ON pt.id=b.part_id
        LEFT JOIN warehouse_areas wa ON wa.id=b.warehouse_area_id
        WHERE 1=1
    '''
    if clauses:
        sql += ' AND ' + ' AND '.join(clauses)
    if status:
        sql += ' AND b.status=?'
        args.append(status)
    if printed in ('0', '1'):
        sql += ' AND b.printed=?'
        args.append(int(printed))
    sql += ' ORDER BY b.created_at DESC, b.id DESC LIMIT 100'
    return ok(rows_to_dicts(query_all(sql, args)))


@bp.get('/boxes/<box_no>')
def get_box(box_no):
    row = box_detail_by_no(box_no)
    if not row:
        return fail('箱号不存在', 404, 'box_not_found')
    return ok(row)


@bp.post('/boxes/mark-printed')
def mark_printed():
    try:
        data = require_json()
        box_nos = data.get('box_nos') or ([data.get('box_no')] if data.get('box_no') else [])
        box_nos = [str(x).strip() for x in box_nos if str(x).strip()]
        if not box_nos:
            return fail('请选择需要标记打印的箱号')
        marked = []
        for box_no in box_nos:
            if query_one('SELECT id FROM boxes WHERE box_no=?', (box_no,)):
                execute('UPDATE boxes SET printed=1, printed_at=? WHERE box_no=?', (now_text(), box_no))
                marked.append(box_no)
        get_db().commit()
        return ok({'box_nos': marked})
    except ValueError as exc:
        return fail(str(exc))


@bp.post('/shipments/preview')
def shipment_preview():
    try:
        data = require_json()
        box_nos = data.get('box_nos') or ([data.get('box_no')] if data.get('box_no') else [])
        rows = []
        for box_no in [str(x).strip() for x in box_nos if str(x).strip()]:
            row = box_detail_by_no(box_no)
            if not row:
                return fail(f'箱号不存在：{box_no}', 404, 'box_not_found')
            if row['status'] != 'in_stock':
                return fail(f'箱号不是库存状态：{box_no}', 409, 'box_not_in_stock')
            rows.append(row)
        if not rows:
            return fail('请先加入出货暂存箱号')
        total_qty = sum(row['qty'] for row in rows)
        return ok({'items': rows, 'total_qty': total_qty, 'box_count': len(rows)})
    except ValueError as exc:
        return fail(str(exc))


def create_shipment_record(data):
    box_nos = [str(x).strip() for x in (data.get('box_nos') or []) if str(x).strip()]
    if not box_nos and data.get('box_no'):
        box_nos = [str(data.get('box_no')).strip()]
    if not box_nos:
        raise ValueError('请先加入出货暂存箱号')
    rows = []
    for box_no in box_nos:
        row = box_detail_by_no(box_no)
        if not row:
            raise LookupError(f'箱号不存在：{box_no}')
        if row['status'] != 'in_stock':
            raise RuntimeError(f'箱号不是库存状态：{box_no}')
        rows.append(row)
    shipment_no = str(data.get('shipment_no', '')).strip() or f'SHP-{datetime.now().strftime("%Y%m%d%H%M%S")}'
    customer_id = optional_positive_int(data.get('customer_id'), '客户')
    execute('INSERT INTO shipments (shipment_no, customer_id, remark) VALUES (?, ?, ?)', (shipment_no, customer_id, data.get('remark', '')))
    shipment_id = query_one('SELECT id FROM shipments WHERE shipment_no=?', (shipment_no,))['id']
    shipped_at = now_text()
    for row in rows:
        execute("UPDATE boxes SET status='shipped', shipped_at=? WHERE box_no=?", (shipped_at, row['box_no']))
        execute('''
            INSERT INTO shipment_items (shipment_id, box_id, box_no, order_id, order_item_id, product_id, part_id, qty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (shipment_id, row['id'], row['box_no'], row['order_id'], row['order_item_id'], row['product_id'], row['part_id'], row['qty']))
        execute('''
            INSERT INTO stock_moves (move_type, box_no, order_id, order_item_id, product_id, part_id, warehouse_area_id, qty, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('ship', row['box_no'], row['order_id'], row['order_item_id'], row['product_id'], row['part_id'], row['warehouse_area_id'], row['qty'], f'出货单 {shipment_no}'))
        if row['order_item_id']:
            execute('UPDATE order_items SET shipped_qty=shipped_qty+? WHERE id=?', (row['qty'], row['order_item_id']))
    return shipment_detail(shipment_id)


@bp.post('/shipments')
def create_shipment():
    try:
        data = require_json()
        shipment = create_shipment_record(data)
        get_db().commit()
        return ok(shipment, 201)
    except LookupError as exc:
        get_db().rollback()
        return fail(str(exc), 404, 'box_not_found')
    except RuntimeError as exc:
        get_db().rollback()
        return fail(str(exc), 409, 'box_not_in_stock')
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


def shipment_detail(shipment_id):
    shipment = row_to_dict(query_one('''
        SELECT s.*, c.code AS customer_code, c.name AS customer_name
        FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id
        WHERE s.id=?
    ''', (shipment_id,)))
    shipment['items'] = rows_to_dicts(query_all('''
        SELECT si.*, o.order_no, p.code AS product_code, p.name AS product_name,
               pt.code AS part_code, pt.name AS part_name, pt.spec, pt.color, pt.unit
        FROM shipment_items si
        LEFT JOIN orders o ON o.id=si.order_id
        LEFT JOIN products p ON p.id=si.product_id
        JOIN parts pt ON pt.id=si.part_id
        WHERE si.shipment_id=?
        ORDER BY si.id
    ''', (shipment_id,)))
    shipment['total_qty'] = sum(item['qty'] for item in shipment['items'])
    return shipment


@bp.get('/shipments')
def shipments():
    clauses, args = query_filters([('q', '(s.shipment_no LIKE ? OR c.name LIKE ? OR si.box_no LIKE ? OR pt.name LIKE ?)')])
    if args:
        args = args * 4
    sql = '''
        SELECT s.*, c.code AS customer_code, c.name AS customer_name,
               COUNT(si.id) AS box_count, COALESCE(SUM(si.qty),0) AS total_qty
        FROM shipments s
        LEFT JOIN customers c ON c.id=s.customer_id
        LEFT JOIN shipment_items si ON si.shipment_id=s.id
        LEFT JOIN parts pt ON pt.id=si.part_id
        WHERE 1=1
    '''
    if clauses:
        sql += ' AND ' + ' AND '.join(clauses)
    sql += ' GROUP BY s.id, c.code, c.name ORDER BY s.created_at DESC, s.id DESC'
    return ok(rows_to_dicts(query_all(sql, args)))


@bp.post('/ship')
def ship_compat():
    try:
        data = require_json()
        shipment = create_shipment_record({'box_no': data.get('box_no'), 'remark': data.get('note', '')})
        get_db().commit()
        return ok(shipment, 201)
    except LookupError as exc:
        get_db().rollback()
        return fail(str(exc), 404, 'box_not_found')
    except RuntimeError as exc:
        get_db().rollback()
        return fail(str(exc), 409, 'box_not_in_stock')
    except ValueError as exc:
        get_db().rollback()
        return fail(str(exc))


@bp.post('/returns')
def return_box():
    try:
        data = require_json()
        box_no = str(data.get('box_no', '')).strip()
        reason = str(data.get('reason', '')).strip()
        row = query_one('SELECT * FROM boxes WHERE box_no=?', (box_no,))
        if not row:
            return fail('箱号不存在', 404, 'box_not_found')
        stamp = now_text()
        execute("UPDATE boxes SET status='returned', returned_at=? WHERE box_no=?", (stamp, box_no))
        execute("INSERT INTO defects (product_id, part_id, order_id, qty, reason, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                (row['product_id'], row['part_id'], row['order_id'], row['qty'], reason))
        execute('''
            INSERT INTO stock_moves (move_type, box_no, order_id, order_item_id, product_id, part_id, warehouse_area_id, qty, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('return', box_no, row['order_id'], row['order_item_id'], row['product_id'], row['part_id'], row['warehouse_area_id'], row['qty'], reason or '客户退回复检'))
        get_db().commit()
        return ok(box_detail_by_no(box_no))
    except ValueError as exc:
        return fail(str(exc))


@bp.get('/stock-moves')
def stock_moves():
    clauses, args = query_filters([('q', '(sm.box_no LIKE ? OR sm.note LIKE ? OR p.name LIKE ? OR pt.name LIKE ?)')])
    if args:
        args = args * 4
    move_type = request.args.get('move_type', '').strip()
    sql = '''
        SELECT sm.*, o.order_no, p.code AS product_code, p.name AS product_name,
               pt.code AS part_code, pt.name AS part_name, wa.code AS area_code, wa.name AS area_name
        FROM stock_moves sm
        LEFT JOIN orders o ON o.id=sm.order_id
        LEFT JOIN products p ON p.id=sm.product_id
        LEFT JOIN parts pt ON pt.id=sm.part_id
        LEFT JOIN warehouse_areas wa ON wa.id=sm.warehouse_area_id
        WHERE 1=1
    '''
    if clauses:
        sql += ' AND ' + ' AND '.join(clauses)
    if move_type:
        sql += ' AND sm.move_type=?'
        args.append(move_type)
    sql += ' ORDER BY sm.created_at DESC, sm.id DESC LIMIT 200'
    return ok(rows_to_dicts(query_all(sql, args)))


@bp.get('/stock-moves.csv')
def export_stock_moves():
    rows = query_all('SELECT * FROM stock_moves ORDER BY created_at DESC')
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'move_type', 'box_no', 'order_id', 'order_item_id', 'product_id', 'part_id', 'warehouse_area_id', 'qty', 'note', 'created_at'])
    for row in rows:
        writer.writerow([row['id'], row['move_type'], row['box_no'], row['order_id'], row['order_item_id'], row['product_id'], row['part_id'], row['warehouse_area_id'], row['qty'], row['note'], row['created_at']])
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
