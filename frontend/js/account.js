/* 회원 탈퇴 (UX-018) · workplace.html 의 #withdraw 창
   POST /auth/withdraw {password} → 성공하면 이 탭의 로그인 정보를 지우고 login.html?withdrawn=1
   비밀번호가 틀리면(400 PASSWORD_MISMATCH) 창을 닫지 않고 칸 아래에 안내 */
(function ($, S) {
  'use strict';
  $(function () {
    var busy = false;
    $(document).on('click', '[data-open-withdraw]', function (e) {
      e.preventDefault();
      $('#withdraw-pw').val('');
      S.clearError($('#withdraw-pw'));
      S.openModal('withdraw');
    });
    $('#withdraw-form').on('safet:submit', function (e) {
      e.preventDefault();
      if (busy) return;
      busy = true;
      var $ok = $('#withdraw-ok').prop('disabled', true).text('처리 중');
      S.api.post('/auth/withdraw', { password: $('#withdraw-pw').val() })
        .done(function () {
          S.hasUnsaved = function () { return false; };
          S.auth.clear();
          try { sessionStorage.clear(); } catch (err) { /* 무시 */ }
          window.location.replace('login.html?withdrawn=1');
        })
        .fail(function (err) {
          busy = false;
          $ok.prop('disabled', false).text('탈퇴하기');
          S.fieldError($('#withdraw-pw'), err.message || '탈퇴하지 못했어요. 잠시 뒤 다시 시도해 주세요.');
          $('#withdraw-pw').trigger('focus');
        });
    });
  });
})(jQuery, window.SafeT);
