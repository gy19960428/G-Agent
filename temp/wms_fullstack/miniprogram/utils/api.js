function getApiBase() {
  const app = getApp();
  return app.globalData.apiBase.replace(/\/$/, '');
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}${path}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        const body = res.data || {};
        if (res.statusCode < 200 || res.statusCode >= 300 || body.ok === false) {
          reject(new Error((body.error && body.error.message) || body.message || `请求失败：${res.statusCode}`));
          return;
        }
        resolve(body.data);
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络请求失败'));
      }
    });
  });
}

module.exports = {
  getDashboard() {
    return request('/dashboard');
  },
  getBox(boxNo) {
    return request(`/boxes/${encodeURIComponent(boxNo)}`);
  },
  shipBox(boxNo) {
    return request('/ship', { method: 'POST', data: { box_no: boxNo } });
  },
  returnBox(boxNo, reason) {
    return request('/returns', { method: 'POST', data: { box_no: boxNo, reason } });
  }
};
