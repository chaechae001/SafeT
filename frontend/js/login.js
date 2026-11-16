/* =========================================================
   로그인·회원가입 (login.html) · A01 · A02
   - 로그인 유지 기능 없음. 오류는 입력칸 아래에 표시
   - 회원가입: 이메일 → 인증 코드 → 비밀번호 → 이름, 이미 가입한 이메일은 인증 요청 단계에서 안내
   - 가입 직후 사업장 등록(B02 · 첫 등록이면 취소 없음)
   인증·로그인은 API 연결 전이라 화면 흐름만 확인합니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  var requested = false;

  $(function () {
    $('#auth-request').on('click', function () {
      var $email = $('#signup-email');
      var v = $.trim($email.val());
      SafeT.clearError($email);
      if (!v) { SafeT.fieldError($email, '이메일을 입력해 주세요.'); $email.trigger('focus'); return; }
      if (!EMAIL_RE.test(v)) { SafeT.fieldError($email, '이메일 형식을 확인해 주세요.'); $email.trigger('focus'); return; }
      // API 연결 후: 이미 가입한 이메일이면 '이미 가입한 이메일이에요. 로그인해 주세요.' 를 칸 아래에 표시
      requested = true;
      $(this).text('다시 요청');
      SafeT.toast('인증 코드를 보냈어요. (API 연결 전 예시)');
      $('#auth_code').trigger('focus');
    });

    $('#auth_code').on('input', function () {
      this.value = this.value.replace(/\D/g, '').slice(0, 6);
    });

    $('#signup-form').on('safet:validate', function (e) {
      if (!requested) {
        e.preventDefault();
        SafeT.fieldError($('#signup-email'), '먼저 인증 요청을 눌러 주세요.');
      } else if ($('#auth_code').val().length !== 6) {
        e.preventDefault();
        SafeT.fieldError($('#auth_code'), '6자리 코드를 입력해 주세요.');
      }
    });

    $('#pw-reset').on('click', function (e) {
      e.preventDefault();
      SafeT.toast('비밀번호 재설정은 API 연결 후 동작해요.');
    });
  });
})(jQuery, window.SafeT);
