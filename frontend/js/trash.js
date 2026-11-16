/* =========================================================
   휴지통 (trash.html) · H02
   - 작성 중 초안만 30일 보관, 복원하면 작성 중 탭으로
   - 영구 삭제는 복원 불가 안내 후 실행
   삭제·복원은 API 연결 전이라 화면 안에서만 반영합니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  $(function () {
    var $target = $();

    $('#v-trash').on('click', 'a[href="#purge-1"]', function () {
      $target = $(this).closest('.card');
      $('#purge-1-title').text('‘' + $.trim($target.find('.card__title').text()) + '’을 영구 삭제할까요?');
    });

    $('#purge-1').on('click', '.btn--danger', function (e) {
      e.preventDefault();
      $target.remove();
      $target = $();
      SafeT.toast('영구 삭제했어요.');
      SafeT.go('v-trash');
      if (!$('#v-trash .card-list .card').length) {
        $('#v-trash .card-list').append('<li class="empty">휴지통이 비어 있어요.</li>');
      }
    });

    // 복원: 이전 입력 내용 그대로 작성 중 탭으로 (탭 상태를 '작성 중'으로 맞춤)
    $('#v-trash').on('click', 'a[href="home.html"]', function () {
      try {
        var s = JSON.parse(window.sessionStorage.getItem('safet.home') || '{}');
        s.tab = 'W';
        s.page = 1;
        s.scroll = 0;
        window.sessionStorage.setItem('safet.home', JSON.stringify(s));
      } catch (err) { /* 저장 불가 환경 */ }
    });
  });
})(jQuery, window.SafeT);
