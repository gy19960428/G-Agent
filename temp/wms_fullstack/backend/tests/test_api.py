import os
import tempfile

import pytest

from app import create_app
from app.db import init_db


@pytest.fixture()
def client():
    fd, db_path = tempfile.mkstemp()
    os.close(fd)
    app = create_app({'TESTING': True, 'DATABASE_URL': f'sqlite:///{db_path}'})
    with app.app_context():
        init_db()
    with app.test_client() as client:
        yield client
    os.unlink(db_path)


def test_health(client):
    res = client.get('/api/health')
    assert res.status_code == 200
    assert res.get_json()['ok'] is True


def test_business_flow(client):
    customer = client.post('/api/customers', json={
        'code': 'C001',
        'name': '楼上精密电子',
        'contact': '张工',
    })
    assert customer.status_code == 201
    customer_id = customer.get_json()['data']['id']

    part = client.post('/api/parts', json={
        'code': 'PT001',
        'name': '充电器插脚',
        'unit': 'pcs',
    })
    assert part.status_code == 201
    part_id = part.get_json()['data']['id']

    product = client.post('/api/products', json={
        'code': 'P001',
        'name': '充电器外壳主体',
        'spec': '黑色',
        'pack_qty': 100,
        'customer_id': customer_id,
        'components': [{'part_id': part_id, 'qty': 2}],
    })
    assert product.status_code == 201
    product_data = product.get_json()['data']
    product_id = product_data['id']
    assert product_data['customer_id'] == customer_id
    assert product_data['components'][0]['part_id'] == part_id

    bom = client.get(f'/api/products/{product_id}/parts')
    assert bom.status_code == 200
    assert bom.get_json()['data'][0]['qty'] == 2

    order = client.post('/api/orders', json={
        'order_no': 'ORD-2026-001',
        'product_id': product_id,
        'customer_id': customer_id,
        'total_qty': 1000,
    })
    assert order.status_code == 201
    order_data = order.get_json()['data']
    order_id = order_data['id']
    assert order_data['customer_id'] == customer_id

    box = client.post('/api/produce', json={'order_id': order_id, 'qty': 100, 'box_no': 'BX-TEST-001'})
    assert box.status_code == 201
    assert box.get_json()['data']['status'] == 'in_stock'

    found = client.get('/api/boxes/BX-TEST-001')
    assert found.status_code == 200
    assert found.get_json()['data']['product_code'] == 'P001'

    shipped = client.post('/api/ship', json={'box_no': 'BX-TEST-001'})
    assert shipped.status_code == 200
    assert shipped.get_json()['data']['status'] == 'shipped'

    duplicated = client.post('/api/ship', json={'box_no': 'BX-TEST-001'})
    assert duplicated.status_code == 409

    returned = client.post('/api/returns', json={'box_no': 'BX-TEST-001', 'reason': '外观复检'})
    assert returned.status_code == 200
    assert returned.get_json()['data']['status'] == 'returned'

    products = client.get('/api/products')
    assert products.status_code == 200
    assert products.get_json()['data'][0]['customer_name'] == '楼上精密电子'

    orders = client.get('/api/orders')
    assert orders.status_code == 200
    assert orders.get_json()['data'][0]['customer_name'] == '楼上精密电子'

    dashboard = client.get('/api/dashboard')
    assert dashboard.status_code == 200
    stats = dashboard.get_json()['data']
    assert stats['customers'] == 1
    assert stats['parts'] == 1
    assert stats['returned_boxes'] == 1
    assert stats['returned_qty'] == 100
    assert stats['open_qty'] == 1000
