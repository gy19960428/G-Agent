const defaultApi = `${window.location.protocol}//${window.location.hostname}:5000/api`;
let API_BASE = localStorage.getItem('wms_api_base') || defaultApi;
let currentUser = JSON.parse(localStorage.getItem('wms_user') || 'null');
let cache = { customers: [], parts: [], products: [], orders: [], boxes: [], areas: [], shipments: [], users: [], settings: {} };
let shipmentDraft = [];
let confirmHandler = null;
let editState = {};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function toast(message, isError = false) {
  const node = $('#toast');
  node.textContent = message;
  node.style.background = isError ? '#dc2626' : '#111827';
  node.classList.add('show');
  clearTimeout(node.timer);
  node.timer = setTimeout(() => node.classList.remove('show'), 2600);
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (currentUser?.username) headers['X-WMS-User'] = currentUser.username;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const contentType = res.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok || payload.ok === false) {
    throw new Error(payload?.error?.message || payload?.message || `请求失败：${res.status}`);
  }
  return payload.data ?? payload;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function asNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function formData(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  Object.keys(data).forEach((key) => {
    if (data[key] === '') delete data[key];
    else if (['customer_id', 'part_id', 'product_id', 'order_id', 'order_item_id', 'warehouse_area_id', 'qty', 'box_capacity', 'standard_qty', 'unit_weight', 'server_port'].includes(key)) data[key] = Number(data[key]);
  });
  return data;
}

function renderTable(table, columns, rows, emptyText = '暂无数据') {
  if (!table) return;
  if (!rows.length) {
    table.innerHTML = `<tr><td class="empty">${escapeHtml(emptyText)}</td></tr>`;
    return;
  }
  table.innerHTML = `
    <thead><tr>${columns.map((c) => `<th class="${c.className || ''}">${escapeHtml(c.label)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${columns.map((c) => `<td class="${c.className || ''}">${c.render ? c.render(row) : escapeHtml(row[c.key])}</td>`).join('')}</tr>`).join('')}</tbody>
  `;
}

function fillSelect(select, rows, labelFn, placeholder = '请选择') {
  if (!select) return;
  const old = select.value;
  select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` + rows.map((row) => `<option value="${row.id}">${escapeHtml(labelFn(row))}</option>`).join('');
  if (old) select.value = old;
}

function filterRows(rows, keyword, fields) {
  const kw = String(keyword || '').trim().toLowerCase();
  if (!kw) return rows;
  return rows.filter((row) => fields.some((field) => String(row[field] ?? '').toLowerCase().includes(kw)) || JSON.stringify(row).toLowerCase().includes(kw));
}

function statusText(status) {
  return { packed: '已装箱', in_stock: '库存中', shipped: '已出货', returned: '已退回', qc_failed: '质检异常' }[status] || status || '';
}

function partLabel(part) {
  return `${part.code || ''} ${part.name || ''}${part.spec ? ` / ${part.spec}` : ''}${part.color ? ` / ${part.color}` : ''}`.trim();
}

function productLabel(product) {
  return `${product.code || ''} ${product.name || ''}`.trim();
}

function selectedProducePart() {
  const partId = Number($('#producePart')?.value || 0);
  return cache.parts.find((part) => Number(part.id) === partId) || null;
}

function syncProduceQtyRequirement() {
  const input = $('#produceForm input[name="qty"]');
  const part = selectedProducePart();
  if (!input) return;
  input.required = part?.count_method === 'weight';
  input.placeholder = part?.count_method === 'weight' ? '本箱数量（称重部件必填）' : '本箱数量，不填按每箱数量';
}

function orderItemLabel(item) {
  const name = item.part_name || item.product_name || '';
  const code = item.part_code || item.product_code || '';
  return `${item.order_no || ''} - ${code} ${name}（未交 ${asNumber(item.open_qty, item.qty)}）`;
}

function renderDashboard(data) {
  const items = [
    ['客户数', data.customers || 0],
    ['产品数', data.products || 0],
    ['部件数', data.parts || 0],
    ['订单数', data.orders || 0],
    ['未交货数', data.open_qty || 0],
    ['库存数量', data.stock_qty || 0],
    ['库存箱数', data.in_stock_boxes || 0],
    ['已出货数', data.shipped_qty || 0],
  ];
  $('#dashboard').innerHTML = items.map(([label, num]) => `<div class="card"><div class="label">${label}</div><div class="num">${num}</div></div>`).join('');
  renderOverviewCharts();
}

function renderMiniChart(title, rows) {
  const max = Math.max(1, ...rows.map((row) => asNumber(row.value)));
  return `<div class="mini-chart"><h3>${escapeHtml(title)}</h3>${rows.map((row) => {
    const value = asNumber(row.value);
    return `<div class="bar-row"><span>${escapeHtml(row.label)}</span><div class="bar-track"><i style="width:${Math.max(4, Math.round(value / max * 100))}%"></i></div><b>${escapeHtml(value)}</b></div>`;
  }).join('')}</div>`;
}

function renderOverviewCharts() {
  const node = $('#overviewCharts');
  if (!node) return;
  const rows = filterRows(cache.boxes, $('#overviewKeyword')?.value, ['box_no', 'order_no', 'product_name', 'part_name', 'warehouse_area_name']);
  const statuses = ['packed', 'in_stock', 'shipped', 'returned', 'qc_failed'].map((status) => ({ label: statusText(status), value: rows.filter((row) => row.status === status).length }));
  const topParts = Object.entries(rows.reduce((acc, row) => {
    const key = row.part_name || row.product_name || '未分类';
    acc[key] = (acc[key] || 0) + asNumber(row.qty);
    return acc;
  }, {})).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([label, value]) => ({ label, value }));
  node.innerHTML = renderMiniChart('箱号状态分布', statuses) + renderMiniChart('部件库存/流转数量 Top 8', topParts.length ? topParts : [{ label: '暂无数据', value: 0 }]);
}

function adminActions(type, id) {
  if (!isAdmin()) return null;
  return `<div class="row-actions"><button data-action="edit" data-type="${type}" data-id="${id}" type="button">编辑</button><button class="danger" data-action="delete" data-type="${type}" data-id="${id}" type="button">删除</button></div>`;
}

function renderCustomers() {
  const rows = filterRows(cache.customers, $('#customerKeyword')?.value, ['code', 'name', 'contact', 'phone']);
  renderTable($('#customersTable'), [
    { key: 'code', label: '编码', className: 'code-col' },
    { key: 'name', label: '客户' },
    { key: 'contact', label: '联系人' },
    { key: 'phone', label: '电话' },
    { key: 'address', label: '地址', className: 'text-col' },
    { key: 'remark', label: '备注', className: 'text-col' },
    { key: 'actions', label: '操作', className: 'action-col', render: (row) => adminActions('customers', row.id) },
  ], rows, '暂无客户');
}

function renderParts() {
  const rows = filterRows(cache.parts, $('#partKeyword')?.value, ['code', 'name', 'spec', 'color', 'unit', 'count_method']);
  renderTable($('#partsTable'), [
    { key: 'code', label: '编码', className: 'code-col' },
    { key: 'name', label: '部件' },
    { key: 'spec', label: '规格' },
    { key: 'color', label: '颜色' },
    { key: 'unit', label: '单位', className: 'compact-col' },
    { key: 'standard_qty', label: '理论数', className: 'num-col' },
    { key: 'box_capacity', label: '每箱', className: 'num-col' },
    { key: 'count_method', label: '计数', className: 'compact-col' },
    { key: 'actions', label: '操作', className: 'action-col', render: (row) => adminActions('parts', row.id) },
  ], rows, '暂无部件');
}

function isAdmin() {
  return currentUser?.role === 'admin';
}

function renderAuthState() {
  const loggedIn = Boolean(currentUser);
  $('#loginPage')?.classList.toggle('hidden', loggedIn);
  $('#appShell')?.classList.toggle('hidden', !loggedIn);
  $$('.admin-only').forEach((node) => { node.hidden = !isAdmin(); });
  const badge = $('#userBadge');
  if (badge) badge.textContent = currentUser ? `${currentUser.username} / ${currentUser.role === 'admin' ? '管理员' : '普通人员'}` : '';
  const logoutBtn = $('#logoutBtn');
  if (logoutBtn) logoutBtn.hidden = !currentUser;
  const active = $('#tabs button.active');
  if (loggedIn && active?.hidden) $('#tabs button:not([hidden])')?.click();
}

function renderProducts() {
  const rows = filterRows(cache.products, $('#productKeyword')?.value, ['code', 'name', 'customer_name', 'remark']);
  renderTable($('#productsTable'), [
    { key: 'code', label: '产品编码', className: 'code-col' },
    { key: 'name', label: '产品名称' },
    { key: 'customer_name', label: '客户' },
    { key: 'parts', label: 'BOM 部件', className: 'bom-cell', render: (row) => (row.parts || []).map((p) => `${escapeHtml(p.part_code)} ${escapeHtml(p.part_name)} × ${escapeHtml(p.ratio_qty)}`).join('<br>') || '-' },
    { key: 'remark', label: '备注', className: 'text-col' },
    { key: 'actions', label: '操作', className: 'action-col', render: (row) => adminActions('products', row.id) },
  ], rows, '暂无产品');
}

function renderOrders() {
  const rows = filterRows(cache.orders, $('#orderKeyword')?.value, ['order_no', 'customer', 'customer_name', 'remark']);
  renderTable($('#ordersTable'), [
    { key: 'order_no', label: '订单号', className: 'code-col' },
    { key: 'customer_name', label: '客户', render: (row) => escapeHtml(row.customer_name || row.customer || '') },
    { key: 'items', label: '明细', className: 'bom-cell', render: (row) => (row.items || []).map((i) => `${escapeHtml(i.product_code || i.part_code || '')} ${escapeHtml(i.product_name || i.part_name || '')}：${escapeHtml(i.qty)}，已出 ${escapeHtml(i.shipped_qty || 0)}，未交 ${escapeHtml(i.open_qty ?? (i.qty - (i.shipped_qty || 0)))}`).join('<br>') },
    { key: 'open_qty', label: '未交', className: 'num-col' },
    { key: 'due_date', label: '交期', className: 'date-col' },
    { key: 'actions', label: '操作', className: 'action-col', render: (row) => adminActions('orders', row.id) },
  ], rows, '暂无订单');
}

function boxColumns({ selectable = false, actions = false } = {}) {
  const cols = [];
  if (selectable) cols.push({ key: 'select', label: '选', className: 'select-col', render: (row) => `<input type="checkbox" class="box-check" value="${escapeHtml(row.box_no)}">` });
  cols.push(
    { key: 'box_no', label: '箱号', className: 'code-col' },
    { key: 'part_name', label: '部件', render: (row) => escapeHtml(row.part_name || row.product_name || '') },
    { key: 'qty', label: '数量', className: 'num-col' },
    { key: 'status', label: '状态', className: 'status-col', render: (row) => `<span class="status-${escapeHtml(row.status)}">${escapeHtml(statusText(row.status))}</span>` },
    { key: 'warehouse_area_name', label: '库区', className: 'compact-col' },
    { key: 'printed_at', label: '面签', className: 'date-col', render: (row) => row.printed_at ? escapeHtml(row.printed_at) : '<span class="warn">未打印</span>' },
    { key: 'order_no', label: '订单', className: 'code-col' }
  );
  if (actions) cols.push({ key: 'actions', label: '操作', className: 'action-col', render: (row) => `<button type="button" class="print-one" data-box="${escapeHtml(row.box_no)}">面签打印</button>` });
  return cols;
}

function renderBoxes() {
  const stockStatus = $('#stockStatus')?.value ?? 'in_stock';
  const stockRows = filterRows(cache.boxes, $('#stockKeyword')?.value, ['box_no', 'order_no', 'product_name', 'part_name', 'warehouse_area_name'])
    .filter((row) => !stockStatus || row.status === stockStatus);
  const unprinted = cache.boxes.filter((row) => !row.printed_at && row.status === 'packed');
  renderOverviewCharts();
  renderTable($('#packingBoxesTable'), boxColumns({ selectable: true, actions: true }), unprinted, '暂无未打印面签箱号');
  renderTable($('#packingRecentBoxesTable'), [
    { key: 'created_at', label: '创建时间', className: 'date-col' },
    { key: 'box_no', label: '箱号', className: 'code-col' },
    { key: 'part_name', label: '部件', render: (row) => escapeHtml(row.part_name || row.product_name || '') },
    { key: 'qty', label: '数量', className: 'num-col' },
    { key: 'created_by', label: '创建人', className: 'compact-col', render: (row) => escapeHtml(row.created_by || '-') },
    { key: 'status', label: '状态', className: 'status-col', render: (row) => `<span class="status-${escapeHtml(row.status)}">${escapeHtml(statusText(row.status))}</span>` },
  ], cache.boxes.slice(0, 100), '暂无箱号记录');
  renderTable($('#boxesTable'), boxColumns(), stockRows, '暂无库存记录');
}

function renderShipments() {
  const rows = filterRows(cache.shipments, $('#shipmentKeyword')?.value, ['shipment_no', 'customer_name', 'remark']);
  renderTable($('#shipmentsTable'), [
    { key: 'shipment_no', label: '出货单号', className: 'code-col' },
    { key: 'customer_name', label: '客户' },
    { key: 'total_qty', label: '数量', className: 'num-col' },
    { key: 'item_count', label: '箱数', className: 'num-col' },
    { key: 'created_at', label: '生成时间', className: 'date-col' },
    { key: 'remark', label: '备注', className: 'text-col' },
  ], rows, '暂无出货单');
  renderShipmentDraft();
}

function renderShipmentDraft() {
  renderTable($('#shipmentDraftTable'), [
    { key: 'box_no', label: '箱号', className: 'code-col' },
    { key: 'part_name', label: '部件', render: (row) => escapeHtml(row.part_name || row.product_name || '') },
    { key: 'qty', label: '数量', className: 'num-col' },
    { key: 'remove', label: '操作', className: 'action-col', render: (row) => `<button type="button" class="remove-draft" data-box="${escapeHtml(row.box_no)}">移除</button>` },
  ], shipmentDraft, '请先扫描箱号加入暂存');
}

function renderSettings() {
  const settingsForm = $('#settingsForm');
  if (settingsForm && cache.settings) {
    ['company_name', 'server_host', 'server_port'].forEach((key) => {
      if (settingsForm.elements[key]) settingsForm.elements[key].value = cache.settings[key] ?? '';
    });
  }
  renderTable($('#usersTable'), [
    { key: 'username', label: '账号', className: 'code-col' },
    { key: 'role', label: '角色', render: (row) => row.role === 'admin' ? '管理员' : '普通人员' },
    { key: 'active', label: '状态', render: (row) => row.active ? '启用' : '停用' },
    { key: 'created_at', label: '创建时间', className: 'code-col' },
  ], cache.users || [], '暂无人员');
  renderTable($('#areasTable'), [
    { key: 'code', label: '编码', className: 'code-col' },
    { key: 'name', label: '库区' },
    { key: 'remark', label: '备注', className: 'text-col' },
  ], cache.areas || [], '暂无库区');
}

function renderAll() {
  renderAuthState();
  renderCustomers();
  renderParts();
  renderProducts();
  renderOrders();
  renderBoxes();
  renderShipments();
  renderSettings();
  fillSelect($('#productCustomer'), cache.customers, (r) => `${r.code} ${r.name}`, '选择客户');
  fillSelect($('#orderCustomer'), cache.customers, (r) => `${r.code} ${r.name}`, '选择客户');
  fillSelect($('#shipmentCustomer'), cache.customers, (r) => `${r.code} ${r.name}`, '选择客户');
  fillSelect($('#stockArea'), cache.areas, (r) => r.name, '选择库区');
  const orderItems = cache.orders.flatMap((order) => (order.items || []).filter((item) => asNumber(item.open_qty, item.qty) > 0).map((item) => ({ ...item, order_no: order.order_no })));
  fillSelect($('#produceOrderItem'), orderItems, orderItemLabel, '选择订单明细');
  syncBuilderSelects();
}

async function loadAll() {
  const [dashboard, customers, parts, products, orders, boxes, areas, shipments] = await Promise.all([
    api('/dashboard'), api('/customers'), api('/parts'), api('/products'), api('/orders'), api('/boxes'), api('/warehouse-areas'), api('/shipments')
  ]);
  let users = cache.users || [];
  let settings = cache.settings || {};
  if (isAdmin()) {
    [users, settings] = await Promise.all([api('/users'), api('/settings')]);
  }
  cache = { customers, parts, products, orders, boxes, areas, shipments, users, settings };
  renderDashboard(dashboard);
  renderAll();
}

function addBomRow(value = {}) {
  const row = document.createElement('div');
  row.className = 'line-row bom-row';
  row.innerHTML = `<select class="bom-part" required></select><input class="bom-ratio" type="number" min="0.001" step="0.001" value="${escapeHtml(value.ratio_qty || 1)}" placeholder="比例数量"><button type="button" class="remove-line secondary">删除</button>`;
  $('#bomRows').appendChild(row);
  fillSelect(row.querySelector('select'), cache.parts, partLabel, '选择部件');
  if (value.part_id) row.querySelector('select').value = value.part_id;
}

function addOrderItemRow(value = {}) {
  const row = document.createElement('div');
  row.className = 'line-row order-item-row';
  row.innerHTML = `<select class="order-kind"><option value="part">部件</option><option value="product">产品</option></select><select class="order-target" required></select><input class="order-qty" type="number" min="1" value="${escapeHtml(value.qty || '')}" placeholder="订单数量"><button type="button" class="remove-line secondary">删除</button>`;
  $('#orderItemRows').appendChild(row);
  const kind = row.querySelector('.order-kind');
  if (value.product_id) kind.value = 'product';
  syncOrderTarget(row);
  if (value.part_id) row.querySelector('.order-target').value = value.part_id;
  if (value.product_id) row.querySelector('.order-target').value = value.product_id;
}

function syncOrderTarget(row) {
  const kind = row.querySelector('.order-kind').value;
  fillSelect(row.querySelector('.order-target'), kind === 'product' ? cache.products : cache.parts, kind === 'product' ? productLabel : partLabel, kind === 'product' ? '选择产品' : '选择部件');
}

function syncBuilderSelects() {
  $$('.bom-row').forEach((row) => {
    const old = row.querySelector('select').value;
    fillSelect(row.querySelector('select'), cache.parts, partLabel, '选择部件');
    row.querySelector('select').value = old;
  });
  $$('.order-item-row').forEach(syncOrderTarget);
}

function openConfirm(title, html, handler) {
  $('#confirmTitle').textContent = title;
  $('#confirmBody').innerHTML = html;
  confirmHandler = handler;
  $('#confirmModal').classList.remove('hidden');
}

function closeConfirm() {
  $('#confirmModal').classList.add('hidden');
  confirmHandler = null;
}

function boxesDetailHtml(rows) {
  return `<div class="table-wrap compact-table"><table><thead><tr><th>箱号</th><th>部件</th><th>数量</th><th>订单</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.box_no)}</td><td>${escapeHtml(row.part_name || row.product_name || '')}</td><td>${escapeHtml(row.qty)}</td><td>${escapeHtml(row.order_no || '')}</td></tr>`).join('')}</tbody></table></div>`;
}

async function markPrinted(boxNos) {
  await api('/boxes/mark-printed', { method: 'POST', body: JSON.stringify({ box_nos: boxNos }) });
  window.print();
  await loadAll();
  toast('面签已标记为已打印');
}

async function submitSimpleForm(form, path, message, transform = (data) => data) {
  const payload = transform(formData(form));
  await api(path, { method: 'POST', body: JSON.stringify(payload) });
  form.reset();
  await loadAll();
  toast(message);
}

function setFormValues(form, data, fields) {
  fields.forEach((name) => {
    if (form.elements[name]) form.elements[name].value = data[name] ?? '';
  });
}

function setEditState(type, id) {
  editState[type] = id;
}

function clearEditState(type, form, title, button) {
  const labels = {
    customers: ['新增客户', '新增客户'],
    parts: ['新增部件', '新增部件'],
    products: ['新增产品与 BOM', '新增产品'],
    orders: ['新增订单', '新增订单'],
  };
  delete editState[type];
  form.reset();
  if (title) title.textContent = labels[type]?.[0] || title.textContent;
  if (button) button.textContent = labels[type]?.[1] || button.textContent;
}

async function submitManagedForm(type, form, path, createMessage, updateMessage, transform = (data) => data, afterSave = () => {}) {
  const id = editState[type];
  const payload = transform(formData(form));
  await api(id ? `${path}/${id}` : path, { method: id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
  clearEditState(type, form, form.querySelector('h2'), form.querySelector('button[type="submit"], button:not([type])'));
  await afterSave();
  await loadAll();
  toast(id ? updateMessage : createMessage);
}

function switchPage(pageName) {
  const btn = $(`#tabs button[data-page="${pageName}"]`);
  if (btn) btn.click();
}

function editCustomer(row) {
  switchPage('customers');
  const form = $('#customerForm');
  setEditState('customers', row.id);
  setFormValues(form, row, ['code', 'name', 'contact', 'phone', 'address', 'remark']);
  form.querySelector('h2').textContent = '编辑客户';
  form.querySelector('button:not([type])').textContent = '保存客户';
}

function editPart(row) {
  switchPage('parts');
  const form = $('#partForm');
  setEditState('parts', row.id);
  setFormValues(form, row, ['code', 'name', 'spec', 'color', 'unit', 'box_capacity', 'count_method', 'remark']);
  form.querySelector('h2').textContent = '编辑部件';
  form.querySelector('button:not([type])').textContent = '保存部件';
}

function editProduct(row) {
  switchPage('product-entry');
  const form = $('#productForm');
  setEditState('products', row.id);
  setFormValues(form, row, ['code', 'name', 'remark']);
  $('#bomRows').innerHTML = '';
  (row.components || []).forEach((item) => addBomRow(item));
  if (!row.components?.length) addBomRow();
  form.querySelector('h2').textContent = '编辑产品与 BOM';
  form.querySelector('button:not([type])').textContent = '保存产品';
}

function editOrder(row) {
  switchPage('orders');
  const form = $('#orderForm');
  setEditState('orders', row.id);
  setFormValues(form, row, ['customer_id', 'order_no', 'due_date', 'remark']);
  $('#orderItemRows').innerHTML = '';
  (row.items || []).forEach((item) => addOrderItemRow(item));
  if (!row.items?.length) addOrderItemRow();
  form.querySelector('h2').textContent = '编辑订单';
  form.querySelector('button:not([type])').textContent = '保存订单';
}

function handleManagedAction(btn) {
  const { action, type, id } = btn.dataset;
  const row = (cache[type] || []).find((item) => String(item.id) === String(id));
  if (!row) return toast('记录不存在，请刷新后重试', true);
  if (action === 'edit') {
    ({ customers: editCustomer, parts: editPart, products: editProduct, orders: editOrder }[type])?.(row);
    return;
  }
  if (action === 'delete') {
    openConfirm('确认删除记录', `<p>将删除：<strong>${escapeHtml(row.code || row.order_no || row.name || id)}</strong></p><p class="hint">删除后不可在列表中使用，请确认。</p>`, async () => {
      await api(`/${type}/${id}`, { method: 'DELETE' });
      await loadAll();
      toast('记录已删除');
    });
  }
}

function initEvents() {
  $('#apiBase').value = API_BASE;
  $('#exportCsv').href = `${API_BASE}/stock-moves.csv`;

  $('#tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-page]');
    if (!btn) return;
    $$('#tabs button').forEach((node) => node.classList.toggle('active', node === btn));
    $$('.page').forEach((page) => page.classList.toggle('active', page.id === `page-${btn.dataset.page}`));
  });

  $('#apiBase').value = API_BASE;
  $('#saveApi').addEventListener('click', async () => {
    API_BASE = ($('#apiBase').value.trim() || defaultApi).replace(/\/$/, '');
    localStorage.setItem('wms_api_base', API_BASE);
    $('#exportCsv').href = `${API_BASE}/stock-moves.csv`;
    if (currentUser) await loadAll();
    toast('API 地址已保存');
  });
  $('#refreshBtn').addEventListener('click', () => loadAll().then(() => toast('已刷新')).catch((err) => toast(err.message, true)));
  $('#loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      currentUser = await api('/login', { method: 'POST', body: JSON.stringify({ username: $('#loginUser').value.trim(), password: $('#loginPass').value }) });
      localStorage.setItem('wms_user', JSON.stringify(currentUser));
      await loadAll();
      toast('登录成功');
    } catch (err) { toast(err.message, true); }
  });
  $('#logoutBtn').addEventListener('click', () => {
    currentUser = null;
    localStorage.removeItem('wms_user');
    renderAuthState();
    toast('已退出');
  });

  $('#customerForm').addEventListener('submit', (e) => {
    e.preventDefault();
    submitManagedForm('customers', e.target, '/customers', '客户已新增', '客户已保存').catch((err) => toast(err.message, true));
  });
  $('#partForm').addEventListener('submit', (e) => {
    e.preventDefault();
    submitManagedForm('parts', e.target, '/parts', '部件已新增', '部件已保存').catch((err) => toast(err.message, true));
  });
  $('#productForm').addEventListener('submit', (e) => {
    e.preventDefault();
    submitManagedForm('products', e.target, '/products', '产品已新增', '产品已保存', (data) => {
      data.components = $$('.bom-row').map((row) => ({ part_id: Number(row.querySelector('.bom-part').value), ratio_qty: Number(row.querySelector('.bom-ratio').value || 1) })).filter((row) => row.part_id);
      return data;
    }, async () => { $('#bomRows').innerHTML = ''; addBomRow(); }).catch((err) => toast(err.message, true));
  });
  $('#orderForm').addEventListener('submit', (e) => {
    e.preventDefault();
    submitManagedForm('orders', e.target, '/orders', '订单已新增', '订单已保存', (data) => {
      data.items = $$('.order-item-row').map((row) => {
        const kind = row.querySelector('.order-kind').value;
        const id = Number(row.querySelector('.order-target').value);
        return { [kind === 'product' ? 'product_id' : 'part_id']: id, qty: Number(row.querySelector('.order-qty').value) };
      }).filter((row) => (row.product_id || row.part_id) && row.qty > 0);
      data.total_qty = data.items.reduce((sum, row) => sum + Number(row.qty || 0), 0);
      return data;
    }, async () => { $('#orderItemRows').innerHTML = ''; addOrderItemRow(); }).catch((err) => toast(err.message, true));
  });
  $('#produceForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const part = selectedProducePart();
    submitSimpleForm(e.target, '/produce', '箱号已生成', (data) => {
      if (!part) throw new Error('请选择部件');
      const boxCount = Number(data.box_count || 1);
      if (!Number.isInteger(boxCount) || boxCount < 1 || boxCount > 100) throw new Error('生成箱数必须是 1-100');
      if (data.box_no && boxCount > 1) throw new Error('手工箱号一次只能生成 1 箱');
      data.box_count = boxCount;
      if (part.count_method === 'weight' && !data.qty) throw new Error('称重部件必须填写本箱数量');
      if (!data.qty && part.box_capacity) data.qty = Number(part.box_capacity);
      return data;
    }).then(syncProduceQtyRequirement).catch((err) => toast(err.message, true));
  });
  $('#stockInForm').addEventListener('submit', (e) => { e.preventDefault(); submitSimpleForm(e.target, '/stock-in', '已入库').catch((err) => toast(err.message, true)); });
  $('#settingsForm').addEventListener('submit', (e) => { e.preventDefault(); submitSimpleForm(e.target, '/settings', '服务器设置已保存').catch((err) => toast(err.message, true)); });
  $('#userForm').addEventListener('submit', (e) => { e.preventDefault(); submitSimpleForm(e.target, '/users', '人员已新增').catch((err) => toast(err.message, true)); });
  $('#areaForm').addEventListener('submit', (e) => { e.preventDefault(); submitSimpleForm(e.target, '/warehouse-areas', '库存区已新增').catch((err) => toast(err.message, true)); });

  $('#addBomRow').addEventListener('click', () => addBomRow());
  $('#addOrderItemRow').addEventListener('click', () => addOrderItemRow());
  document.body.addEventListener('click', async (e) => {
    if (e.target.matches('.remove-line')) e.target.closest('.line-row')?.remove();
    if (e.target.matches('.remove-draft')) {
      shipmentDraft = shipmentDraft.filter((row) => row.box_no !== e.target.dataset.box);
      renderShipmentDraft();
    }
    if (e.target.matches('.print-one')) {
      const row = cache.boxes.find((item) => item.box_no === e.target.dataset.box);
      openConfirm('确认打印面签', boxesDetailHtml([row]), () => markPrinted([row.box_no]));
    }
  });
  document.body.addEventListener('change', (e) => {
    if (e.target.matches('.order-kind')) syncOrderTarget(e.target.closest('.order-item-row'));
    if (e.target.matches('#producePart')) syncProduceQtyRequirement();
  });

  ['overviewKeyword', 'customerKeyword', 'partKeyword', 'productKeyword', 'orderKeyword', 'stockKeyword', 'stockStatus', 'shipmentKeyword'].forEach((id) => {
    $(`#${id}`)?.addEventListener('input', renderAll);
    $(`#${id}`)?.addEventListener('change', renderAll);
  });

  $('#batchPrintBtn').addEventListener('click', () => {
    const boxNos = $$('.box-check:checked').map((node) => node.value);
    if (!boxNos.length) return toast('请先勾选要打印的箱号', true);
    const rows = cache.boxes.filter((row) => boxNos.includes(row.box_no));
    openConfirm('确认批量打印面签', boxesDetailHtml(rows), () => markPrinted(boxNos));
  });

  $('#shipScanForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = e.target.elements.box_no;
    const boxNo = input.value.trim();
    if (!boxNo) return;
    if (shipmentDraft.some((row) => row.box_no === boxNo)) return toast('该箱号已在暂存区', true);
    try {
      const row = await api(`/boxes/${encodeURIComponent(boxNo)}`);
      if (row.status !== 'in_stock') throw new Error(`箱号不是库存状态：${boxNo}`);
      shipmentDraft.push(row);
      input.value = '';
      renderShipmentDraft();
      toast('已加入出货暂存');
    } catch (err) { toast(err.message, true); }
  });

  $('#shipmentForm').addEventListener('submit', (e) => {
    e.preventDefault();
    if (!shipmentDraft.length) return toast('请先加入出货暂存箱号', true);
    const payload = formData(e.target);
    payload.box_nos = shipmentDraft.map((row) => row.box_no);
    openConfirm('确认生成出货单', boxesDetailHtml(shipmentDraft), async () => {
      await api('/shipments', { method: 'POST', body: JSON.stringify(payload) });
      shipmentDraft = [];
      e.target.reset();
      closeConfirm();
      await loadAll();
      toast('出货单已生成');
    });
  });
  ['customersTable', 'partsTable', 'productsTable', 'ordersTable'].forEach((tableId) => {
    $(`#${tableId}`).addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-action]');
      if (btn) handleManagedAction(btn);
    });
  });
  $('#clearShipmentDraft').addEventListener('click', () => { shipmentDraft = []; renderShipmentDraft(); });
  $('#closeModal').addEventListener('click', closeConfirm);
  $('#confirmAction').addEventListener('click', async () => {
    if (!confirmHandler) return;
    try { await confirmHandler(); closeConfirm(); } catch (err) { toast(err.message, true); }
  });

  addBomRow();
  addOrderItemRow();
  syncProduceQtyRequirement();
}

initEvents();
renderAuthState();
if (currentUser) {
  loadAll().catch((err) => toast(err.message, true));
}
