(function() {
  function getApiBase() {
    var saved = localStorage.getItem('crm_api_base');
    if (saved) return saved.replace(/\/$/, '');

    if (window.location.protocol === 'file:' || ['localhost', '127.0.0.1'].indexOf(window.location.hostname) !== -1) {
      return 'http://127.0.0.1:8000';
    }

    return window.location.origin.replace(/\/$/, '');
  }

  function getToken() {
    return localStorage.getItem('crm_token') || '';
  }

  function getCurrentUser() {
    var raw = localStorage.getItem('crm_user');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (error) {
      return null;
    }
  }

  function requireAuth(permissionKey) {
    var user = getCurrentUser();
    if (!user || !getToken()) {
      window.location.href = 'login.html';
      return null;
    }

    if (
      permissionKey &&
      user.permissions &&
      Object.prototype.hasOwnProperty.call(user.permissions, permissionKey) &&
      !user.permissions[permissionKey]
    ) {
      alert('当前账号无权访问此页面');
      window.location.href = 'crm-system.html';
      return null;
    }

    return user;
  }

  async function apiRequest(path, options) {
    var opts = options ? Object.assign({}, options) : {};
    var headers = Object.assign({}, opts.headers || {});
    var body = opts.body;

    if (body && !(body instanceof FormData) && typeof body === 'object') {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }

    if (getToken()) {
      headers.Authorization = 'Bearer ' + getToken();
    }

    opts.headers = headers;
    opts.body = body;

    var response = await fetch(getApiBase() + path, opts);
    var payload = null;

    if (response.status !== 204) {
      var text = await response.text();
      payload = text ? JSON.parse(text) : null;
    }

    if (!response.ok) {
      var message = payload && (payload.detail || payload.message) ? (payload.detail || payload.message) : '请求失败';
      if (response.status === 401) {
        localStorage.removeItem('crm_user');
        localStorage.removeItem('crm_token');
        window.location.href = 'login.html';
      }
      throw new Error(message);
    }

    return payload;
  }

  function isAdmin(user) {
    return !!user && user.role === 'admin';
  }

  function canEditOwner(user, ownerId) {
    if (!user) return false;
    if (user.role === 'admin' || user.role === 'manager') return true;
    return String(user.id) === String(ownerId || '');
  }

  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  window.CRMApp = {
    apiRequest: apiRequest,
    canEditOwner: canEditOwner,
    escapeHtml: escapeHtml,
    getApiBase: getApiBase,
    getCurrentUser: getCurrentUser,
    getToken: getToken,
    isAdmin: isAdmin,
    requireAuth: requireAuth
  };
})();
