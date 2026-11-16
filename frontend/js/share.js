/* =========================================================
   결과 공유 (share.html) · 받는 사람 화면 (share-download.html) · SHARE
   - 평가표당 링크 1개(7일). 공유 중지·재발급 시 이전 링크는 바로 막힘
   - 앱 안에서 메신저로 직접 보내지 않음(링크 복사·QR)
   - 열람·다운로드는 결과 확인·서명으로 기록하지 않음(다운로드 횟수만)
   링크 발급·PDF 생성은 API 연결 전입니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // 대체: 입력칸 선택 후 복사
    var $tmp = $('<textarea class="sr-only">').val(text).appendTo('body');
    $tmp.get(0).select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    $tmp.remove();
    return ok ? Promise.resolve() : Promise.reject();
  }

  $(function () {
    $('#copy-link').on('click', function () {
      var url = $('#share_url').val();
      copyText(url).then(function () {
        SafeT.toast('링크를 복사했어요. 메신저에 붙여 넣어 보내 주세요.');
      }, function () {
        $('#share_url').trigger('focus').get(0).select();
        SafeT.toast('복사하지 못했어요. 선택된 링크를 직접 복사해 주세요.');
      });
    });

    $('#share-stop').on('click', function () {
      SafeT.closeModal();
      SafeT.go('v-share');
      $('#share_url').val('공유 중지됨');
      $('#copy-link').prop('disabled', true);
      $('#share-expire').text('공유를 중지했어요. 이전 링크는 열리지 않아요.');
      SafeT.toast('공유를 중지했어요.');
    });

    $('#share-reissue').on('click', function () {
      SafeT.closeModal();
      SafeT.go('v-share');
      SafeT.toast('새 링크 발급은 API 연결 후 동작해요.');
    });

    $('#pdf-download').on('click', function () {
      SafeT.toast('PDF 다운로드는 API 연결 후 동작해요.');
    });
  });
})(jQuery, window.SafeT);
