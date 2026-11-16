/* =========================================================
   Safe-T 공통 API 호출 (api.js) · jQuery
   - API 주소: 화면과 같은 호스트의 8001번 포트 (window.SAFET_API_BASE 로 바꿀 수 있음)
   - 오류는 { status, code, message, field?, ... } 한 가지 모양으로 바꿔 돌려줍니다.
     백엔드 오류 형식(임시): {"detail": {"code", "message"}} / 입력 형식 오류(422): {"detail": [{loc, msg}]}
   - API 키·DB 비밀번호는 여기에 넣지 않습니다.
   ========================================================= */
(function ($, window) {
  'use strict';

  var SafeT = window.SafeT = window.SafeT || {};
  var loc = window.location;
  var BASE = window.SAFET_API_BASE ||
    (loc.protocol === 'file:' ? 'http://localhost:8001' : loc.protocol + '//' + loc.hostname + ':8001');

  function toError(xhr, textStatus) {
    if (xhr.status === 0) {
      return {
        status: 0,
        code: textStatus === 'timeout' ? 'TIMEOUT' : 'NETWORK',
        message: textStatus === 'timeout'
          ? '응답이 늦어요. 잠시 뒤 다시 시도해 주세요.'
          : '서버에 연결할 수 없어요. API 서버가 켜져 있는지 확인해 주세요.'
      };
    }
    var d = xhr.responseJSON && xhr.responseJSON.detail;
    if (d && typeof d === 'object' && !$.isArray(d) && d.message) {
      return $.extend({ status: xhr.status }, d);
    }
    if ($.isArray(d) && d.length) {                    // FastAPI 입력 형식 오류 (422)
      var e = d[0];
      var field = e.loc && e.loc.length ? e.loc[e.loc.length - 1] : null;
      var msg = String(e.msg || '').replace(/^Value error,\s*/, '');
      return { status: xhr.status, code: 'INVALID', field: field, message: msg || '입력값을 확인해 주세요.' };
    }
    return { status: xhr.status, code: 'ERROR', message: '요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.' };
  }

  /* ---------- 로그인 토큰 (JWT) ----------
     sessionStorage 에 보관: 브라우저 탭을 닫으면 로그아웃 (설계서 07쪽 '로그인 유지 기능 없음') */
  var TOKEN_KEY = 'safet.token';
  var USER_KEY = 'safet.user';

  function store(fn) {
    try { return fn(window.sessionStorage); } catch (err) { return null; }
  }

  SafeT.auth = {
    token: function () { return store(function (s) { return s.getItem(TOKEN_KEY); }); },
    user: function () {
      var u = store(function (s) { return s.getItem(USER_KEY); });
      try { return u ? JSON.parse(u) : null; } catch (err) { return null; }
    },
    save: function (res) {
      store(function (s) {
        s.setItem(TOKEN_KEY, res.access_token);
        s.setItem(USER_KEY, JSON.stringify({ email: res.email, name: res.name }));
      });
    },
    clear: function () {
      store(function (s) { s.removeItem(TOKEN_KEY); s.removeItem(USER_KEY); });
    }
  };

  /* ---------- 로그인 확인 · 만료 후 복구 (설계서 07쪽) ----------
     <body data-auth-required> 화면은 로그인해야 볼 수 있습니다.
     - 로그인 안 함 → login.html?required=1, 로그인하면 원래 화면으로
     - 토큰 만료 → 보던 화면 주소와 화면별 편집 내용(onExpire)을 저장하고 login.html?expired=1
       다시 로그인하면 그 화면으로 돌아가고, 화면이 takeRestore() 로 편집 내용을 되살립니다. */
  var RETURN_KEY = 'safet.return';
  var RESTORE_KEY = 'safet.restore';
  var EVAL_KEY = 'safet.eval';
  var expireHooks = [];
  var leaving = false;

  /* ---------- 지금 보는 평가표 번호 (2026-11-16) ----------
     주소에 ?eval= 로 드러내지 않고 이 탭의 sessionStorage 에 둡니다.
     - 내 평가표에서 카드·버튼을 누를 때 저장 → draft.html / result.html / sign.html / share.html 이 읽음
     - 같은 탭이면 새로 고침·다른 화면에 다녀와도 유지. 새 탭·주소 복사로는 전달되지 않음
     - 주소에서 숨기는 것은 번호를 바꿔 보는 가벼운 시도를 줄이는 정도입니다.
       남의 평가표를 실제로 막는 것은 서버의 소유자 확인(평가표 API 에서 반드시 확인). */
  SafeT.current = {
    setEval: function (no) {
      store(function (s) { if (no) s.setItem(EVAL_KEY, String(no)); else s.removeItem(EVAL_KEY); });
    },
    evalNo: function () {
      var v = store(function (s) { return s.getItem(EVAL_KEY); });
      return v && /^\d+$/.test(v) ? +v : null;
    }
  };

  function readJson(key) {
    var raw = store(function (s) { return s.getItem(key); });
    try { return raw ? JSON.parse(raw) : null; } catch (err) { return null; }
  }

  function me() {
    var u = SafeT.auth.user();
    return u && u.email ? String(u.email).toLowerCase() : null;
  }

  function here() {
    var page = window.location.pathname.split('/').pop() || 'home.html';
    return page + window.location.search + window.location.hash;
  }

  /** 같은 폴더의 화면 주소만 허용 (다른 사이트로 보내지 않음) */
  function safePage(u) {
    return /^[a-z][a-z0-9\-]*\.html([?#].*)?$/i.test(u || '') ? u : null;
  }

  /** 토큰의 만료 시각(초). 화면에서 만료 시점을 알기 위한 용도로만 읽습니다(검증은 서버). */
  function tokenExp(t) {
    try {
      var p = t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      while (p.length % 4) p += '=';
      return JSON.parse(window.atob(p)).exp || null;
    } catch (err) {
      return null;
    }
  }

  /** 화면별 편집 내용 저장 함수 등록: fn() → { page: '화면 이름', data: {...} } */
  SafeT.auth.onExpire = function (fn) { expireHooks.push(fn); };

  /**
   * 로그인 성공 직후: 저장된 돌아갈 화면·복구 정보가 다른 사용자 것이면 모두 지움 (2026-11-16 보완)
   * 사용자 정보가 없는 예전 형식도 지움. 다른 사용자면 '지금 보는 평가표'도 지움
   */
  SafeT.auth.forgetOthers = function (email) {
    var who = String(email || '').toLowerCase();
    var ret = readJson(RETURN_KEY);
    var res = readJson(RESTORE_KEY);
    // 돌아갈 화면: 주인이 없으면(로그인 안 한 채 화면을 연 경우) 지금 로그인한 사람 것으로 봄
    var retOther = ret && ret.owner && ret.owner !== who;
    var other = retOther || (res && res.owner !== who);
    if (retOther) store(function (s) { s.removeItem(RETURN_KEY); });
    if (res && res.owner !== who) store(function (s) { s.removeItem(RESTORE_KEY); });
    if (other) SafeT.current.setEval(null);
    // 예전 형식(문자열)으로 남은 값 정리
    store(function (s) {
      ['safet.return', 'safet.restore'].forEach(function (k) {
        var v = s.getItem(k);
        if (v && v.charAt(0) !== '{') s.removeItem(k);
      });
    });
  };

  /**
   * 로그인 후 돌아갈 화면 (한 번 꺼내면 지움)
   * - 만료로 온 경우: 같은 사용자일 때만
   * - 로그인 안 한 채 화면을 열어 온 경우(주인 없음): 지금 로그인한 사람에게 (편집 내용 복원은 없음)
   */
  SafeT.auth.takeReturn = function (email) {
    var r = readJson(RETURN_KEY);
    store(function (s) { s.removeItem(RETURN_KEY); });
    if (!r || (r.owner && r.owner !== String(email || '').toLowerCase())) return null;
    return safePage(r.url);
  };

  /** 만료 전에 저장한 편집 내용 — 같은 사용자·같은 화면·같은 평가표일 때만 (한 번 꺼내면 지움) */
  SafeT.auth.takeRestore = function (page) {
    var r = readJson(RESTORE_KEY);
    if (!r) return null;
    store(function (s) { s.removeItem(RESTORE_KEY); });     // 맞지 않으면 버림 (다른 평가표에 덮이지 않게)
    var ok = r.owner && r.owner === me() && r.page === page && r.eval === SafeT.current.evalNo();
    return ok ? r.data : null;
  };

  /** 로그인 화면으로 보내기. reason: 'required' | 'expired' */
  SafeT.auth.toLogin = function (reason) {
    if (leaving) return;
    leaving = true;
    var owner = me();                      // 로그인 정보를 지우기 전에 누구 것인지 기록 (없으면 null)
    store(function (s) { s.setItem(RETURN_KEY, JSON.stringify({ owner: owner, url: here() })); });
    if (reason === 'expired' && owner) {
      $.each(expireHooks, function (_, fn) {
        try {
          var r = fn();
          if (r && r.page) {
            store(function (s) {
              s.setItem(RESTORE_KEY, JSON.stringify({
                owner: owner, page: r.page, eval: SafeT.current.evalNo(), data: r.data
              }));
            });
          }
        } catch (err) { /* 저장 실패해도 로그인 화면으로는 보냄 */ }
      });
    }
    SafeT.auth.clear();
    window.location.replace('login.html?' + (reason === 'expired' ? 'expired' : 'required') + '=1');
  };

  /** 로그아웃: 묻고 → 토큰·복구 정보 삭제 → 로그인 화면 */
  SafeT.auth.logout = function () {
    var unsaved = typeof SafeT.hasUnsaved === 'function' && SafeT.hasUnsaved();
    SafeT.confirm(unsaved ? {
      title: '저장하지 않은 수정이 있어요',
      message: '지금 로그아웃하면 저장하지 않은 수정이 사라져요. 로그아웃할까요?',
      ok: '로그아웃',
      cancel: '계속 작성',
      danger: true
    } : {
      title: '로그아웃할까요?',
      message: '다시 로그인해야 화면을 볼 수 있어요.',
      ok: '로그아웃',
      cancel: '취소'
    }).then(function (yes) {
      if (yes !== true) return;
      SafeT.auth.clear();
      store(function (s) { s.removeItem(RETURN_KEY); s.removeItem(RESTORE_KEY); s.removeItem(EVAL_KEY); });
      window.location.href = 'login.html?logout=1';
    });
  };

  // 메뉴의 '로그아웃' (화면별 '나가기 확인'보다 먼저 처리)
  $(document).on('click', '.menu__list a[href="login.html"]', function (e) {
    e.preventDefault();
    e.stopImmediatePropagation();
    $('details.menu[open]').prop('open', false);
    SafeT.auth.logout();
  });

  // 로그인이 필요한 화면: 토큰 확인 → 만료 시각 예약 → 서버에 한 번 더 확인
  $(function () {
    if (!document.body.hasAttribute('data-auth-required')) return;
    var t = SafeT.auth.token();
    if (!t) { SafeT.auth.toLogin('required'); return; }
    var exp = tokenExp(t);
    if (exp) {
      var ms = exp * 1000 - Date.now();
      if (ms <= 0) { SafeT.auth.toLogin('expired'); return; }
      setTimeout(function () { SafeT.auth.toLogin('expired'); }, ms);
    }
    $('body').addClass('auth-ok');
    request('GET', '/auth/me');      // 401 이면 아래 request() 에서 로그인 화면으로 (서버가 꺼져 있으면 그대로 둠)
  });

  function request(method, path, body) {
    var d = $.Deferred();
    var token = SafeT.auth.token();
    $.ajax({
      url: BASE + path,
      method: method,
      headers: token ? { Authorization: 'Bearer ' + token } : {},
      contentType: body ? 'application/json' : undefined,
      data: body ? JSON.stringify(body) : undefined,
      dataType: 'json',
      timeout: method === 'POST' && (path === '/evals' || /^\/evals\/\d+\/(risk-answers|items)$/.test(path)) ? 150000 : 15000
    }).done(function (res) {
      d.resolve(res);
    }).fail(function (xhr, textStatus) {
      if (xhr.status >= 200 && xhr.status < 300) {     // 204 등 본문 없는 성공
        d.resolve(null);
        return;
      }
      var err = toError(xhr, textStatus);
      // 토큰을 보냈는데 401 → 만료·무효: 로그인 화면으로 (로그인 요청 자체의 실패는 제외)
      if (token && err.status === 401 && (err.code === 'TOKEN_EXPIRED' || err.code === 'LOGIN_REQUIRED')) {
        SafeT.auth.toLogin(err.code === 'TOKEN_EXPIRED' ? 'expired' : 'required');
      }
      d.reject(err);
    });
    return d.promise();
  }

  SafeT.api = {
    base: BASE,
    get: function (path) { return request('GET', path); },
    post: function (path, body) { return request('POST', path, body || {}); },
    put: function (path, body) { return request('PUT', path, body || {}); },
    del: function (path) { return request('DELETE', path); }
  };
})(jQuery, window);
