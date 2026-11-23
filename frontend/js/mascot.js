/* =========================================================
   Safe-T 도우미 캐릭터
   - 사용자가 고르거나 적기를 머뭇거릴 때(정해진 시간 동안 누름·스크롤·입력이 없을 때) 다음에 채울 칸 옆에 나타나 가리킴
   - 어떤 조작이든 하면 바로 사라짐. 같은 칸에서는 다시 머뭇거릴 때만 다시 나옴
   - 화면 읽기 프로그램에는 말풍선 문장만 알림(aria-live polite), 그림은 숨김. 움직임 줄이기 설정이면 흔들림 없음
   - 사용: SafeT.mascot.watch(function () { return { el: 요소, text: '말풍선' } | null; }, { idle: 8000 })
            SafeT.mascot.stop()
   ========================================================= */
(function ($, SafeT) {
  'use strict';
  if (!SafeT) return;
  // 파란 안전모를 쓴 흰 고양이(원본 그림의 바깥 흰 여백만 잘라 낸 PNG · frontend/public/mascot/). 꾸밈 그림이라 읽기 프로그램에서는 숨김
  var IMG = '<img src="../public/mascot/safet-cat.png?v=20261124" alt="" aria-hidden="true" width="288" height="258" decoding="async" draggable="false">';
  var $m = null, timer = null, getTarget = null, opts = {}, shownFor = null;

  function el() {
    if ($m) return $m;
    $m = $('<div class="mascot" role="status" aria-live="polite" hidden>' +
      '<div class="mascot__bubble"></div><div class="mascot__body">' + IMG + '</div></div>').appendTo('body');
    $m.on('click', hide);
    return $m;
  }
  function hide() { if ($m) $m.prop('hidden', true).removeClass('is-in'); }
  function place(target, text) {
    var $e = el(), r = target.getBoundingClientRect(), vh = window.innerHeight, vw = window.innerWidth;
    var top = 64, bottom = vh;
    $('.topbar:visible').each(function () { top = Math.max(top, this.getBoundingClientRect().bottom + 8); });
    $('.view.is-active .bottom-bar:visible').each(function () { bottom = Math.min(bottom, this.getBoundingClientRect().top - 8); });
    var off = r.bottom < top + 20 ? 'up' : (r.top > bottom - 40 ? 'down' : null);
    // 칸의 제목을 가리지 않게 칸 바로 위에(자리가 없으면 칸 안 위쪽)
    var above = r.top - 70;
    var y = off === 'down' ? bottom - 92 : (off === 'up' ? top + 4 : Math.min(above >= top ? above : Math.max(r.top + 8, top), bottom - 92));
    $e.find('.mascot__bubble').text(off === 'down' ? '아래에서 ' + text : (off === 'up' ? '위에서 ' + text : text));
    $e.attr('data-point', off || 'side').css({ top: Math.round(y) + 'px', right: Math.max(8, Math.round(vw - Math.min(r.right, vw) + 4)) + 'px' });
    $e.prop('hidden', false).removeClass('is-in'); void $e[0].offsetWidth; $e.addClass('is-in');
  }
  function arm() {
    clearTimeout(timer);
    if (!getTarget) return;
    timer = setTimeout(function () {
      var t = getTarget();
      if (!t || !t.el || document.hidden || $('body').hasClass('has-modal')) { arm(); return; }
      shownFor = t.el; place(t.el, t.text);
    }, opts.idle || 8000);
  }
  function activity() { hide(); arm(); }

  SafeT.mascot = {
    watch: function (fn, o) {
      getTarget = fn; opts = o || {};
      $(document).off('.mascot').on('pointerdown.mascot keydown.mascot input.mascot change.mascot', activity);
      $(window).off('.mascot').on('scroll.mascot resize.mascot', activity);
      document.addEventListener('scroll', activity, { capture: true, passive: true });
      arm();
    },
    poke: activity,
    stop: function () { clearTimeout(timer); getTarget = null; hide(); }
  };
})(window.jQuery, window.SafeT);
