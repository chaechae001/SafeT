/* =========================================================
   현장 입력 블록 상태 (write.html 02 현장) · UX-008 (2026-11-21)
   사진·음성·텍스트 블록마다 입력이 있으면 '✓ 입력됨'(.is-filled)으로 표시하고,
   아직 아무것도 입력하지 않았으면 세 블록을 은은하게 강조(.is-empty-all)해 무엇을 할지 보여 줍니다.
   입력 검사·저장(assessment-write.js)은 바꾸지 않습니다.
   ========================================================= */
(function ($) {
  'use strict';
  $(function () {
    var $photo = $('#blk-photo'), $voice = $('#blk-voice'), $text = $('#blk-text');
    if (!$photo.length) return;

    function refresh() {
      var n = $photo.find('.photo-grid .photo').length, p = n > 0;
      var v = $.trim($('#voice_text').val() || '') !== '';
      var t = $.trim($('#file_text').val() || '') !== '';
      $photo.toggleClass('is-filled', p);
      $voice.toggleClass('is-filled', v);
      $text.toggleClass('is-filled', t);
      $('#field-form').toggleClass('is-empty-all', !p && !v && !t);
      // UX-015: 사진 제목 옆 'n장' 배지, 사진이 있으면 '+ 사진 촬영'
      $('#photo-count').text(n + '장').prop('hidden', !p);
      $photo.toggleClass('has-photo', p);
      $('#file-text-count span').text(($('#file_text').val() || '').length);
    }

    $(document).on('input change', '#voice_text, #file_text', refresh);
    // UX-015: 이 화면 하단 안내 문구
    var $disc = $('.disclaimer'), discBase = $disc.text();
    var FIELD_NOTE = '저장된 입력으로 평가표를 작성합니다. 위험 판단 결과는 현장 검토가 필요합니다.';
    function note() { $disc.text($('#v-field').hasClass('is-active') ? FIELD_NOTE : discBase); }
    $('.view').on('safet:show safet:hide', function () { setTimeout(note, 0); });
    $(window).on('hashchange', function () { setTimeout(note, 0); });
    note();
    if (window.MutationObserver) {
      new MutationObserver(refresh).observe($photo.find('.photo-grid')[0], { childList: true });
      var slot = document.getElementById('voice-slot');
      if (slot) new MutationObserver(refresh).observe(slot, { childList: true, subtree: true });
    }
    // 오류 안내(셋 다 비었을 때)가 텍스트 칸에 붙으면 세 블록 모두 강조
    $('#field-form').on('safet:validate', function () { setTimeout(refresh, 0); });
    refresh();

    /* UX-011: 컴퓨터(터치 없음)에서 '사진 촬영' → 웹캠 창에서 찍어 사진으로 추가.
       휴대폰은 input capture 로 카메라가 바로 열림. 웹캠을 못 쓰면 파일 선택으로 대신함 */
    var touch = window.matchMedia && window.matchMedia('(any-pointer: coarse)').matches;
    var $cam = $('#photo-camera'), stream = null;
    function closeCam() {
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
      window.SafeT.closeModal();
    }
    function camModal() {
      var $m = $('#cam-modal');
      if ($m.length) return $m;
      $m = $('<div class="modal" id="cam-modal" role="dialog" aria-modal="true" aria-labelledby="cam-title">' +
        '<div class="modal__box"><div class="modal__head"><h2 class="modal__title" id="cam-title">사진 촬영</h2>' +
        '<button class="modal__close" type="button" data-cam-close aria-label="닫기">X</button></div>' +
        '<div class="modal__body"><video class="cam__video" autoplay playsinline muted></video></div>' +
        '<div class="modal__foot"><button class="btn btn--primary btn--block cam__shot" type="button">📷 촬영</button></div></div></div>').appendTo('body');
      $m.on('click', '[data-cam-close]', closeCam).on('safet:close', function () { if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; } });
      $m.on('click', '.cam__shot', function () {
        var v = $m.find('video')[0];
        if (!v.videoWidth) return;
        var c = document.createElement('canvas');
        var scale = Math.min(1, 1600 / v.videoWidth);
        c.width = Math.round(v.videoWidth * scale); c.height = Math.round(v.videoHeight * scale);
        c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
        c.toBlob(function (blob) {
          try {
            var dt = new DataTransfer();
            dt.items.add(new File([blob], '촬영_' + Date.now() + '.jpg', { type: 'image/jpeg' }));
            $cam[0].files = dt.files;
            $cam.trigger('change');            // 기존 사진 추가 처리(assessment-write.js) 그대로 사용
          } catch (err) { window.SafeT.toast('사진을 추가하지 못했어요. 사진 불러오기를 이용해 주세요.'); }
          closeCam();
        }, 'image/jpeg', 0.85);
      });
      return $m;
    }
    $('#photo-camera-btn').on('click', function (e) {
      if (touch || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;   // 휴대폰: 카메라 바로
      e.preventDefault();
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(function (s) {
        stream = s;
        var $m = camModal();
        $m.find('video')[0].srcObject = s;
        window.SafeT.openModal($m);
      }).catch(function () {
        window.SafeT.toast('카메라를 쓸 수 없어 파일에서 고를게요.');
        $cam.trigger('click');
      });
    });
  });
})(jQuery);
