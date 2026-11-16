/* =========================================================
   참여자 서명 (sign.html) · SIGN ① 참여자 선택 · ② 서명
   - 확인 체크 + 서명 획이 있어야 '서명 저장' 활성
   - 저장한 서명은 정정 불가, 저장은 원형 로딩만
   - 전원 서명 완료 시 '모두 서명했습니다' + 하단 '내 평가표로'
   서명 저장은 API 연결 전이라 화면 안에서만 반영합니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var hasStroke = false;
  var canvas, ctx;

  function selected() {
    var $r = $('#signer-list input:checked');
    return $r.length ? $.trim($r.closest('label').find('b').text()) : '';
  }

  function updatePick() {
    var total = $('#signer-list input').length;
    var done = $('#signer-list input:disabled').length;
    $('#sign-count').text(done + '/' + total);
    if (done === total) {                       // 전원 서명 완료
      $('#sign-done').prop('hidden', false);
      $('#pick-btn').replaceWith('<a class="btn btn--primary" href="home.html">내 평가표로</a>');
      return;
    }
    var name = selected();
    $('#pick-btn').prop('disabled', !name).text(name ? name + '로 서명하기' : '본인 이름을 선택해 주세요');
  }

  function updateSave() {
    $('#sign-save').prop('disabled', !(hasStroke && $('#sign-form input[name="confirm_yn"]').is(':checked')));
  }

  function setupPad() {
    var $pad = $('#sign-pad');
    canvas = $('<canvas class="sign-pad" id="sign-canvas" aria-label="여기에 직접 서명"></canvas>').get(0);
    $pad.replaceWith(canvas);
    ctx = canvas.getContext('2d');
    var drawing = false;

    function resize() {
      var r = canvas.getBoundingClientRect();
      if (!r.width) return;
      var ratio = window.devicePixelRatio || 1;
      canvas.width = r.width * ratio;
      canvas.height = r.height * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = '#1d2420';
      hasStroke = false;
      updateSave();
    }
    function pos(e) {
      var r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    canvas.addEventListener('pointerdown', function (e) {
      drawing = true;
      canvas.setPointerCapture(e.pointerId);
      var p = pos(e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!drawing) return;
      var p = pos(e);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      if (!hasStroke) { hasStroke = true; updateSave(); }
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (t) {
      canvas.addEventListener(t, function () { drawing = false; });
    });

    $('#v-draw').on('safet:show', resize);
    $(window).on('resize', resize);
    resize();
  }

  $(function () {
    setupPad();
    updatePick();
    updateSave();

    $('#signer-list').on('change', 'input', updatePick);

    // ① → ②: 고른 사람 이름으로 서명 화면
    $('#pick-form').on('safet:submit', function (e) {
      e.preventDefault();
      var name = selected();
      $('#draw-name').text(name + ' · 참여 근로자');
      $('#sign-form input[name="confirm_yn"]').prop('checked', false);
      SafeT.go('v-draw');
    });

    $('#sign-form').on('change', 'input[name="confirm_yn"]', updateSave);

    $('#sign-clear').on('click', function () {      // 서명 칸만 비우기
      var r = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, r.width, r.height);
      hasStroke = false;
      updateSave();
    });

    $('#sign-form').on('safet:validate', function (e) {
      if (!hasStroke) {
        e.preventDefault();
        SafeT.toast('서명 칸에 직접 서명해 주세요.');
      }
    });

    $('#sign-form').on('safet:submit', function (e) {
      e.preventDefault();
      var name = selected();
      SafeT.loading(true);
      SafeT.wait(500).then(function () {
        // 서명자·서명 시각 저장 (API 연결 후). 저장한 서명은 정정 불가 → 목록에서 선택 불가로
        var $r = $('#signer-list input:checked');
        var $l = $r.closest('label').addClass('signer--done');
        $r.prop({ checked: false, disabled: true });
        $l.find('.tag').removeClass('tag--warn').text('서명 완료');
        $('#sign-clear').trigger('click');
        SafeT.loading(false);
        SafeT.toast(name + ' 님의 서명을 저장했어요');
        updatePick();
        SafeT.go('v-pick');
      });
    });
  });
})(jQuery, window.SafeT);
