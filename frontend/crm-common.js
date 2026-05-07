(function() {
  // -----------------------------------------------------------------------
  // 工具：API 基础地址
  // -----------------------------------------------------------------------
  function getApiBase() {
    var params = new URLSearchParams(window.location.search);
    var queryValue = params.get('apiBase');
    if (queryValue) {
      var normalizedQueryValue = queryValue.replace(/\/$/, '');
      localStorage.setItem('crm_api_base', normalizedQueryValue);
      return normalizedQueryValue;
    }

    var saved = localStorage.getItem('crm_api_base');
    if (saved) {
      return saved.replace(/\/$/, '');
    }

    var hostname = window.location.hostname;
    var isLocalHost = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
    if (window.location.protocol === 'file:' || (isLocalHost && window.location.port !== '8000')) {
      return 'http://127.0.0.1:8000';
    }

    return window.location.origin.replace(/\/$/, '');
  }

  // -----------------------------------------------------------------------
  // 认证 Session 管理
  // -----------------------------------------------------------------------
  function getToken() {
    return localStorage.getItem('crm_token') || '';
  }

  function getCurrentUser() {
    var raw = localStorage.getItem('crm_user');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function isAdmin(user) {
    return !!user && (user.is_admin === true || user.username === 'admin');
  }

  function isAuthenticated() {
    return !!getCurrentUser() && !!getToken();
  }

  function storeCurrentUser(user) {
    if (!user) return;
    localStorage.setItem('crm_user', JSON.stringify({
      id: user.id,
      username: user.username,
      is_admin: user.is_admin === true,
      loginTime: (getCurrentUser() && getCurrentUser().loginTime) || new Date().toISOString()
    }));
  }

  var _authVerificationPromises = {};

  function clearAuth() {
    localStorage.removeItem('crm_user');
    localStorage.removeItem('crm_token');
    localStorage.removeItem('crm_api_base');
    sessionStorage.removeItem('crm_scoring_options');
    sessionStorage.removeItem('crm_scoring_options_A');
    sessionStorage.removeItem('crm_scoring_options_B');
  }

  function getDefaultPage(user) {
    return isAdmin(user || getCurrentUser()) ? 'page-report.html' : 'page-opportunities.html';
  }

  function redirectToLogin() {
    if ((window.location.pathname || '').split('/').pop() === 'login.html') {
      return;
    }
    window.location.href = 'login.html';
  }

  function redirectToDefault(user) {
    window.location.href = getDefaultPage(user);
  }

  function setAuthSession(user, token, apiBase) {
    localStorage.setItem('crm_user', JSON.stringify({
      id: user.id,
      username: user.username,
      is_admin: user.is_admin === true,
      loginTime: new Date().toISOString()
    }));
    localStorage.setItem('crm_token', token);
    if (apiBase) {
      localStorage.setItem('crm_api_base', apiBase.replace(/\/$/, ''));
    }
  }

  // -----------------------------------------------------------------------
  // 权限检查入口：在每个页面顶部调用
  // -----------------------------------------------------------------------
  function requireAuth(permissionKey) {
    var user = getCurrentUser();
    if (!user || !getToken()) {
      clearAuth();
      redirectToLogin();
      return null;
    }
    if (permissionKey === 'user_management' && !isAdmin(user)) {
      showToast('只有管理员账号可以访问该页面。', 'error');
      window.location.href = 'page-opportunities.html';
      return null;
    }
    verifyAuthSession(permissionKey);
    return user;
  }

  function verifyAuthSession(permissionKey) {
    var cacheKey = permissionKey || 'default';
    if (_authVerificationPromises[cacheKey]) {
      return _authVerificationPromises[cacheKey];
    }

    _authVerificationPromises[cacheKey] = (async function() {
      var token = getToken();
      if (!token) {
        clearAuth();
        redirectToLogin();
        return null;
      }

      var path = permissionKey === 'user_management' ? '/api/admin/session' : '/api/auth/me';
      var response;
      try {
        response = await fetch(getApiBase() + path, {
          headers: {
            Authorization: 'Bearer ' + token
          }
        });
      } catch (error) {
        clearAuth();
        showToast('无法验证登录状态，请重新登录。', 'warning');
        redirectToLogin();
        return null;
      }

      var payload = null;
      if (response.status !== 204) {
        var text = await response.text();
        if (text) {
          try {
            payload = JSON.parse(text);
          } catch (e) {
            payload = { message: text };
          }
        }
      }

      if (response.status === 401) {
        clearAuth();
        showToast('登录已过期，请重新登录。', 'warning');
        redirectToLogin();
        return null;
      }

      if (response.status === 403) {
        if (permissionKey === 'user_management') {
          showToast('只有管理员账号可以访问该页面。', 'error');
          window.location.href = 'page-opportunities.html';
          return null;
        }
        clearAuth();
        redirectToLogin();
        return null;
      }

      if (!response.ok) {
        clearAuth();
        showToast((payload && (payload.detail || payload.message)) || '登录状态校验失败，请重新登录。', 'warning');
        redirectToLogin();
        return null;
      }

      if (permissionKey === 'user_management' && !isAdmin(payload)) {
        showToast('只有管理员账号可以访问该页面。', 'error');
        window.location.href = 'page-opportunities.html';
        return null;
      }

      storeCurrentUser(payload);
      return payload;
    })();

    return _authVerificationPromises[cacheKey];
  }

  // -----------------------------------------------------------------------
  // HTTP 请求封装：统一处理认证、错误提示、401 跳转
  // -----------------------------------------------------------------------

  // 防止多次并发 401 时重复弹提示
  var _authExpiredPrompted = false;

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

    var response;
    try {
      response = await fetch(getApiBase() + path, opts);
    } catch (networkErr) {
      // 网络层错误（断网、CORS 被拒、服务器未启动等）
      throw new Error('网络请求失败，请检查网络连接或服务是否正常运行。');
    }

    var payload = null;
    if (response.status !== 204) {
      var text = await response.text();
      if (text) {
        try {
          payload = JSON.parse(text);
        } catch (e) {
          payload = { message: text };
        }
      }
    }

    if (!response.ok) {
      var message = (payload && (payload.detail || payload.message)) || '请求失败，请稍后重试';

      if (response.status === 401) {
        // Token 过期或无效：给用户一个友好提示，而不是静默跳转
        if (!_authExpiredPrompted) {
          _authExpiredPrompted = true;
          clearAuth();
          showToast('登录已过期，即将跳转到登录页…', 'warning');
          setTimeout(function() {
            _authExpiredPrompted = false;
            redirectToLogin();
          }, 1800);
        }
        throw new Error('登录已过期，请重新登录');
      }

      if (response.status === 403) {
        throw new Error('权限不足：' + message);
      }
      if (response.status === 422) {
        // FastAPI 参数校验错误，提取 detail 数组
        if (Array.isArray(payload && payload.detail)) {
          var details = payload.detail.map(function(d) {
            return (d.loc ? d.loc.join('.') + ': ' : '') + d.msg;
          }).join('；');
          throw new Error('参数错误：' + details);
        }
      }
      if (response.status >= 500) {
        // 优先显示后端返回的具体错误信息（如 AI 调用失败详情），无则返回通用提示
        throw new Error(message && message !== '请求失败，请稍后重试' ? message : '服务器错误（' + response.status + '），请联系管理员。');
      }

      throw new Error(message);
    }

    return payload;
  }

  // -----------------------------------------------------------------------
  // Toast 通知（轻量内联实现，无依赖）
  // -----------------------------------------------------------------------
  var _toastContainer = null;

  function getToastContainer() {
    if (!_toastContainer) {
      _toastContainer = document.createElement('div');
      _toastContainer.id = 'crm-toast-container';
      _toastContainer.style.cssText = [
        'position:fixed',
        'top:20px',
        'right:20px',
        'z-index:99999',
        'display:flex',
        'flex-direction:column',
        'gap:10px',
        'pointer-events:none'
      ].join(';');
      document.body.appendChild(_toastContainer);
    }
    return _toastContainer;
  }

  /**
   * 显示一条 Toast 通知。
   * @param {string} msg    通知内容
   * @param {'info'|'success'|'warning'|'error'} type 类型
   * @param {number} duration 自动消失毫秒数（默认 3000）
   */
  function showToast(msg, type, duration) {
    if (!msg) return;
    if (!document.body) {
      setTimeout(function() {
        showToast(msg, type, duration);
      }, 0);
      return;
    }
    var t = type || 'info';
    var d = duration || 3000;

    var colorMap = {
      info:    { bg: '#0EA5E9', icon: 'ℹ️' },
      success: { bg: '#10B981', icon: '✅' },
      warning: { bg: '#F59E0B', icon: '⚠️' },
      error:   { bg: '#EF4444', icon: '❌' }
    };
    var style = colorMap[t] || colorMap.info;

    var toast = document.createElement('div');
    toast.style.cssText = [
      'background:' + style.bg,
      'color:#fff',
      'padding:12px 18px',
      'border-radius:10px',
      'font-size:14px',
      'line-height:1.5',
      'box-shadow:0 4px 16px rgba(0,0,0,.18)',
      'max-width:360px',
      'pointer-events:auto',
      'opacity:0',
      'transform:translateX(40px)',
      'transition:opacity .25s,transform .25s'
    ].join(';');
    toast.textContent = style.icon + '  ' + msg;

    var container = getToastContainer();
    container.appendChild(toast);

    // 进场动画
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(0)';
      });
    });

    // 自动消失
    setTimeout(function() {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(40px)';
      setTimeout(function() {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 280);
    }, d);
  }

  // -----------------------------------------------------------------------
  // 评分选项工具
  // -----------------------------------------------------------------------
  function normalizeCardType(cardType) {
    var normalized = String(cardType || 'A').trim().toUpperCase();
    return normalized === 'B' ? 'B' : 'A';
  }

  async function getScoringOptions(cardType, forceRefresh) {
    if (typeof cardType === 'boolean') {
      forceRefresh = cardType;
      cardType = 'A';
    }
    var normalizedCardType = normalizeCardType(cardType);
    var cacheKey = 'crm_scoring_options_' + normalizedCardType;

    if (!forceRefresh) {
      var cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        try {
          return JSON.parse(cached);
        } catch (e) {
          sessionStorage.removeItem(cacheKey);
        }
      }
    }

    var payload = await apiRequest('/api/scoring/options?card_type=' + encodeURIComponent(normalizedCardType));
    sessionStorage.setItem(cacheKey, JSON.stringify(payload || {}));
    sessionStorage.setItem('crm_scoring_options', JSON.stringify(payload || {}));
    return payload;
  }

  // -----------------------------------------------------------------------
  // 资源编辑权限判断
  // -----------------------------------------------------------------------
  function canEditOwner(user, ownerId) {
    if (!user) return false;
    if (isAdmin(user)) return true;
    return String(user.id) === String(ownerId || '');
  }

  // -----------------------------------------------------------------------
  // HTML 转义（防 XSS）
  // -----------------------------------------------------------------------
  function escapeHtml(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  // -----------------------------------------------------------------------
  // 全局导出
  // -----------------------------------------------------------------------
  window.CRMApp = {
    apiRequest:       apiRequest,
    getScoringOptions: getScoringOptions,
    canEditOwner:     canEditOwner,
    escapeHtml:       escapeHtml,
    getApiBase:       getApiBase,
    getCurrentUser:   getCurrentUser,
    getDefaultPage:   getDefaultPage,
    getToken:         getToken,
    isAuthenticated:  isAuthenticated,
    isAdmin:          isAdmin,
    clearAuth:        clearAuth,
    redirectToDefault: redirectToDefault,
    redirectToLogin:  redirectToLogin,
    requireAuth:      requireAuth,
    verifyAuthSession: verifyAuthSession,
    setAuthSession:   setAuthSession,
    showToast:        showToast
  };
})();
