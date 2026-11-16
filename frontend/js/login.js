/* =========================================================
   로그인·회원가입 (login.html) · A01 · A02
   회원가입은 백엔드 API 와 연결되어 있습니다 (backend/routers/auth.py).
     ① 인증 요청   POST /auth/signup/code          → 메일로 6자리 코드 (5분 유효, 재요청 60초 뒤)
     ② 코드 확인   POST /auth/signup/code/verify   → 6자리를 다 넣으면 자동 확인 (5번 틀리면 다시 요청)
     ③ 가입하기    POST /auth/signup               → '회원가입이 완료되었습니다' 안내 + 로그인 화면(이메일 채움)
                                                      (2026-11-16 결정. 설계서 07쪽은 바로 B02 로 이동)
   로그인도 API 와 연결되어 있습니다.
     로그인 POST /auth/login → 토큰(JWT)을 sessionStorage 에 저장
       사업장이 있으면 내 평가표(home.html), 없으면 새 사업장 등록(workplace.html?first=1#v-new) (설계서 07쪽)
     로그인 화면을 열면 이전 로그인은 끝냅니다(메뉴의 '로그아웃'도 이 화면으로 옴).
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var state = { requested: null, verified: null, busy: false };
  var timer = null;

  // 오류 코드 → 표시할 입력칸
  var CODE_FIELD = {
    EMAIL_EXISTS: '#signup-email', RESEND_TOO_SOON: '#signup-email', MAIL_NOT_CONFIGURED: '#signup-email',
    MAIL_FAILED: '#signup-email', NETWORK: '#signup-email', TIMEOUT: '#signup-email', ERROR: '#signup-email',
    CODE_NOT_REQUESTED: '#auth_code', CODE_EXPIRED: '#auth_code', CODE_MISMATCH: '#auth_code',
    TOO_MANY_TRIES: '#auth_code', NOT_VERIFIED: '#auth_code', VERIFY_EXPIRED: '#auth_code',
    CODE_ALREADY_USED: '#auth_code', INVALID_VERIFY_TOKEN: '#auth_code'
  };
  var FIELD = { email: '#signup-email', code: '#auth_code', password: '#signup-pw', name: '#name' };

  function email() { return $.trim($('#signup-email').val()).toLowerCase(); }

  function showError(err) {
    var sel = (err.code === 'INVALID' && FIELD[err.field]) || CODE_FIELD[err.code] || '#signup-email';
    SafeT.fieldError($(sel), err.message);
    $(sel).trigger('focus');
  }

  function codeHint(text, ok) {
    var $h = $('#code-hint');
    if (!$h.length) $h = $('<p class="hint" id="code-hint" aria-live="polite">').insertAfter('#auth_code');
    $h.text(text || '').toggleClass('code-ok', !!ok).prop('hidden', !text);
  }

  function countdown(sec) {
    var $b = $('#auth-request');
    var left = sec;
    clearInterval(timer);
    $b.prop('disabled', true).text('다시 요청 (' + left + ')');
    timer = setInterval(function () {
      left -= 1;
      if (left <= 0) {
        clearInterval(timer);
        $b.prop('disabled', false).text('다시 요청');
      } else {
        $b.text('다시 요청 (' + left + ')');
      }
    }, 1000);
  }

  function setVerified(on, token) {
    state.verified = on ? email() : null;
    // 코드 확인 때 받은 일회용 인증 토큰: 메모리에만 두고 가입하기에 함께 보냄 (새로 고침하면 다시 인증)
    state.token = on ? token : null;
    $('#auth_code').prop('readonly', on);
    codeHint(on ? '✓ 이메일 인증을 마쳤어요.' : '', on);
  }

  /** ① 인증 요청 */
  function requestCode() {
    var $email = $('#signup-email');
    var v = email();
    SafeT.clearError($email);
    if (!v) { SafeT.fieldError($email, '이메일을 입력해 주세요.'); $email.trigger('focus'); return; }
    if (!EMAIL_RE.test(v)) { SafeT.fieldError($email, '이메일 형식을 확인해 주세요.'); $email.trigger('focus'); return; }

    var $b = $('#auth-request').prop('disabled', true);
    SafeT.loading(true);
    SafeT.api.post('/auth/signup/code', { email: v })
      .done(function (res) {
        state.requested = v;
        setVerified(false);
        $('#auth_code').val('');
        countdown(res.resend_after || 60);
        codeHint('메일로 보낸 6자리 코드를 ' + Math.round((res.expires_in || 300) / 60) + '분 안에 입력해 주세요.');
        SafeT.toast('인증 코드를 보냈어요. 메일을 확인해 주세요.');
        $('#auth_code').trigger('focus');
      })
      .fail(function (err) {
        if (err.code === 'RESEND_TOO_SOON' && err.retry_after) countdown(err.retry_after);
        else $b.prop('disabled', false);
        showError(err);
      })
      .always(function () { SafeT.loading(false); });
  }

  /** ② 코드 확인 (6자리를 다 넣으면 자동) */
  function verifyCode() {
    var d = $.Deferred();
    var code = $('#auth_code').val();
    if (state.verified === email()) return d.resolve().promise();
    SafeT.clearError($('#auth_code'));
    SafeT.api.post('/auth/signup/code/verify', { email: email(), code: code })
      .done(function (res) { setVerified(true, res.verify_token); d.resolve(); })
      .fail(function (err) {
        if (err.code === 'TOO_MANY_TRIES' || err.code === 'CODE_EXPIRED' || err.code === 'CODE_ALREADY_USED') {
          $('#auth-request').prop('disabled', false).text('다시 요청');
        }
        showError(err);
        d.reject(err);
      });
    return d.promise();
  }

  $(function () {
    $('#auth-request').on('click', requestCode);

    // 회원가입 화면으로 다시 가면 '가입 완료' 안내는 숨김
    $('#v-signup').on('safet:show', function () { $('#signup-done').prop('hidden', true); });

    $('#auth_code').on('input', function () {
      if (this.readOnly) return;
      this.value = this.value.replace(/\D/g, '').slice(0, 6);
      if (this.value.length === 6 && state.requested === email()) verifyCode();
    });

    // 인증한 뒤 이메일을 바꾸면 처음부터 다시
    $('#signup-email').on('input', function () {
      if (state.requested && email() !== state.requested) {
        state.requested = null;
        setVerified(false);
        $('#auth_code').val('');
        codeHint('');
        // 재요청 60초 제한은 이메일마다 따로 → 다른 이메일은 바로 요청 가능
        clearInterval(timer);
        $('#auth-request').prop('disabled', false).text('인증 요청');
      }
    });

    $('#signup-form').on('safet:validate', function (e) {
      if (state.verified === email()) return;
      if (state.requested !== email()) {
        e.preventDefault();
        SafeT.fieldError($('#signup-email'), '먼저 인증 요청을 눌러 주세요.');
      } else if ($('#auth_code').val().length !== 6) {
        e.preventDefault();
        SafeT.fieldError($('#auth_code'), '메일로 받은 6자리 코드를 입력해 주세요.');
      }
    });

    // ③ 가입하기
    $('#signup-form').on('safet:submit', function (e) {
      e.preventDefault();
      if (state.busy) return;                         // 중복 클릭 방지
      var $f = $(this);
      var $btn = $f.find('[type="submit"]').prop('disabled', true);
      state.busy = true;
      SafeT.loading(true);
      verifyCode()
        .then(function () {
          return SafeT.api.post('/auth/signup', {
            email: email(),
            password: $('#signup-pw').val(),
            name: $('#name').val(),
            verify_token: state.token
          }).fail(function (err) {
            // 인증이 만료·무효 → 인증부터 다시 (코드 칸 풀고 다시 요청 가능)
            if (err.code === 'INVALID_VERIFY_TOKEN' || err.code === 'VERIFY_EXPIRED' || err.code === 'NOT_VERIFIED') {
              setVerified(false);
              $('#auth_code').val('');
              clearInterval(timer);
              $('#auth-request').prop('disabled', false).text('다시 요청');
            }
            showError(err);
          });
        })
        .done(function (res) {
          // 가입 완료 → 로그인 화면 (가입한 이메일을 채워 둠)
          var joined = (res && res.email) || email();
          clearInterval(timer);
          $f.get(0).reset();
          state.requested = null;
          setVerified(false);
          state.busy = false;
          $btn.prop('disabled', false);
          $('#auth-request').prop('disabled', false).text('인증 요청');
          $('#login-email').val(joined);
          $('#login-pw').val('');
          $('#signup-done').prop('hidden', false);
          SafeT.go('v-login');
          SafeT.toast('회원가입이 완료되었습니다.');
          $('#login-pw').trigger('focus');
        })
        .fail(function () {
          state.busy = false;
          $btn.prop('disabled', false);
        })
        .always(function () { SafeT.loading(false); });
    });

    /* ---------- 로그인 ---------- */
    SafeT.auth.clear();          // 로그인 화면에 오면 이전 로그인 종료 (로그아웃)

    // 어떻게 왔는지 안내 (api.js 가 붙인 주소 표시)
    var q = window.location.search;
    var notice = /[?&]expired=1/.test(q) ? ['로그인 시간이 지났어요. 다시 로그인하면 보던 화면으로 돌아가요.', 'notice']
      : /[?&]required=1/.test(q) ? ['로그인이 필요해요. 로그인하면 열려던 화면으로 이동해요.', 'notice']
      : /[?&]logout=1/.test(q) ? ['로그아웃했어요.', 'notice notice--done']
      : null;
    if (notice) $('#auth-notice').attr('class', notice[1]).text(notice[0]).prop('hidden', false);
    $('#v-signup').on('safet:show', function () { $('#auth-notice').prop('hidden', true); });

    var LOGIN_FIELD = { email: '#login-email', password: '#login-pw' };

    $('#login-form').on('safet:submit', function (e) {
      e.preventDefault();
      var $f = $(this);
      var $btn = $f.find('[type="submit"]');
      if ($btn.prop('disabled')) return;              // 중복 클릭 방지
      $btn.prop('disabled', true);
      SafeT.loading(true);
      SafeT.api.post('/auth/login', {
        email: $.trim($('#login-email').val()),
        password: $('#login-pw').val()
      }).done(function (res) {
        // 다른 사용자가 남긴 돌아갈 화면·편집 복구 정보는 지움 (같은 탭에서 계정을 바꾼 경우)
        SafeT.auth.forgetOthers(res.email);
        SafeT.auth.save(res);
        // 만료·로그인 필요로 왔으면 원래 화면(같은 사용자만), 아니면 사업장 유무에 따라 (설계서 07쪽)
        var back = SafeT.auth.takeReturn(res.email);
        window.location.href = back || (res.has_workplace ? 'home.html' : 'workplace.html?first=1#v-new');
      }).fail(function (err) {
        // 오류는 입력칸 아래 (이메일 형식은 이메일 칸, 나머지는 비밀번호 칸)
        var sel = (err.code === 'INVALID' && LOGIN_FIELD[err.field]) || '#login-pw';
        SafeT.fieldError($(sel), err.message);
        $(sel).trigger('focus');
        if (sel === '#login-pw') $('#login-pw').val('');
        $btn.prop('disabled', false);
        SafeT.loading(false);
      });
    });

    /* ---------- 비밀번호 재설정 (#v-reset) ----------
       ① 인증 요청 POST /auth/password/code  (가입 여부와 관계없이 같은 안내)
       ② 6자리를 다 넣으면 POST /auth/password/code/verify
       ③ 비밀번호 바꾸기 POST /auth/password/reset → 로그인 화면 (기존 로그인은 모두 끝남) */
    var rs = { requested: null, verified: null, busy: false, timer: null };
    var RESET_FIELD = { email: '#reset-email', code: '#reset-code', password: '#reset-pw' };
    var RESET_CODE_FIELD = {
      RESEND_TOO_SOON: '#reset-email', MAIL_NOT_CONFIGURED: '#reset-email', MAIL_FAILED: '#reset-email',
      NETWORK: '#reset-email', TIMEOUT: '#reset-email', ERROR: '#reset-email',
      CODE_MISMATCH: '#reset-code', CODE_EXPIRED: '#reset-code', TOO_MANY_TRIES: '#reset-code',
      NOT_VERIFIED: '#reset-code', VERIFY_EXPIRED: '#reset-code',
      CODE_ALREADY_USED: '#reset-code', INVALID_VERIFY_TOKEN: '#reset-code'
    };

    function resetEmail() { return $.trim($('#reset-email').val()).toLowerCase(); }

    function resetError(err) {
      var sel = (err.code === 'INVALID' && RESET_FIELD[err.field]) || RESET_CODE_FIELD[err.code] || '#reset-email';
      SafeT.fieldError($(sel), err.message);
      $(sel).trigger('focus');
    }

    function resetHint(text, ok) {
      var $h = $('#reset-hint');
      if (!$h.length) $h = $('<p class="hint" id="reset-hint" aria-live="polite">').insertAfter('#reset-code');
      $h.text(text || '').toggleClass('code-ok', !!ok).prop('hidden', !text);
    }

    function resetCountdown(sec) {
      var $b = $('#reset-request');
      var left = sec;
      clearInterval(rs.timer);
      $b.prop('disabled', true).text('다시 요청 (' + left + ')');
      rs.timer = setInterval(function () {
        left -= 1;
        if (left <= 0) { clearInterval(rs.timer); $b.prop('disabled', false).text('다시 요청'); }
        else $b.text('다시 요청 (' + left + ')');
      }, 1000);
    }

    function resetVerified(on, token) {
      rs.verified = on ? resetEmail() : null;
      rs.token = on ? token : null;          // 일회용 인증 토큰 (메모리에만)
      $('#reset-code').prop('readonly', on);
      resetHint(on ? '✓ 이메일 인증을 마쳤어요. 새 비밀번호를 입력해 주세요.' : '', on);
    }

    $('#v-reset').on('safet:show', function () {
      $('#auth-notice, #signup-done').prop('hidden', true);
      if (!$('#reset-email').val() && $('#login-email').val()) $('#reset-email').val($('#login-email').val());
    });

    $('#reset-request').on('click', function () {
      var $email = $('#reset-email');
      var v = resetEmail();
      SafeT.clearError($email);
      if (!v) { SafeT.fieldError($email, '이메일을 입력해 주세요.'); $email.trigger('focus'); return; }
      if (!EMAIL_RE.test(v)) { SafeT.fieldError($email, '이메일 형식을 확인해 주세요.'); $email.trigger('focus'); return; }
      var $b = $(this).prop('disabled', true);
      SafeT.loading(true);
      SafeT.api.post('/auth/password/code', { email: v })
        .done(function (res) {
          rs.requested = v;
          resetVerified(false);
          $('#reset-code').val('');
          resetCountdown(res.resend_after || 60);
          // 가입 여부와 관계없이 같은 안내
          resetHint('가입된 이메일이면 6자리 코드를 보냈어요. ' + Math.round((res.expires_in || 300) / 60) + '분 안에 입력해 주세요.');
          $('#reset-code').trigger('focus');
        })
        .fail(function (err) {
          if (err.code === 'RESEND_TOO_SOON' && err.retry_after) resetCountdown(err.retry_after);
          else $b.prop('disabled', false);
          resetError(err);
        })
        .always(function () { SafeT.loading(false); });
    });

    function verifyReset() {
      var d = $.Deferred();
      if (rs.verified === resetEmail()) return d.resolve().promise();
      SafeT.clearError($('#reset-code'));
      SafeT.api.post('/auth/password/code/verify', { email: resetEmail(), code: $('#reset-code').val() })
        .done(function (res) { resetVerified(true, res.verify_token); d.resolve(); })
        .fail(function (err) {
          if (err.code === 'TOO_MANY_TRIES' || err.code === 'CODE_EXPIRED' || err.code === 'CODE_ALREADY_USED') {
            $('#reset-request').prop('disabled', false).text('다시 요청');
          }
          resetError(err);
          d.reject(err);
        });
      return d.promise();
    }

    $('#reset-code').on('input', function () {
      if (this.readOnly) return;
      this.value = this.value.replace(/\D/g, '').slice(0, 6);
      if (this.value.length === 6 && rs.requested === resetEmail()) verifyReset();
    });

    $('#reset-email').on('input', function () {
      if (rs.requested && resetEmail() !== rs.requested) {
        rs.requested = null;
        resetVerified(false);
        $('#reset-code').val('');
        resetHint('');
        // 재요청 60초 제한은 이메일마다 따로 → 다른 이메일은 바로 요청 가능
        clearInterval(rs.timer);
        $('#reset-request').prop('disabled', false).text('인증 요청');
      }
    });

    $('#reset-form').on('safet:validate', function (e) {
      if (rs.verified === resetEmail()) return;
      if (rs.requested !== resetEmail()) {
        e.preventDefault();
        SafeT.fieldError($('#reset-email'), '먼저 인증 요청을 눌러 주세요.');
      } else if ($('#reset-code').val().length !== 6) {
        e.preventDefault();
        SafeT.fieldError($('#reset-code'), '메일로 받은 6자리 코드를 입력해 주세요.');
      }
    });

    $('#reset-form').on('safet:submit', function (e) {
      e.preventDefault();
      if (rs.busy) return;
      var $f = $(this);
      var $btn = $f.find('[type="submit"]').prop('disabled', true);
      rs.busy = true;
      SafeT.loading(true);
      verifyReset()
        .then(function () {
          return SafeT.api.post('/auth/password/reset', { email: resetEmail(), password: $('#reset-pw').val(), verify_token: rs.token })
            .fail(function (err) {
              if (err.code === 'INVALID_VERIFY_TOKEN' || err.code === 'VERIFY_EXPIRED' || err.code === 'NOT_VERIFIED') {
                resetVerified(false);
                $('#reset-code').val('');
                clearInterval(rs.timer);
                $('#reset-request').prop('disabled', false).text('다시 요청');
              }
              resetError(err);
            });
        })
        .done(function () {
          var done = resetEmail();
          clearInterval(rs.timer);
          $f.get(0).reset();
          rs.requested = null;
          resetVerified(false);
          $('#reset-request').prop('disabled', false).text('인증 요청');
          $('#login-email').val(done);
          $('#login-pw').val('');
          $('#auth-notice').attr('class', 'notice notice--done').text('비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.').prop('hidden', false);
          SafeT.go('v-login');
          $('#login-pw').trigger('focus');
        })
        .always(function () {
          rs.busy = false;
          $btn.prop('disabled', false);
          SafeT.loading(false);
        });
    });
  });
})(jQuery, window.SafeT);
