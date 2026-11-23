/* =========================================================
   초안 목록 항목 삭제
   1) 필터 줄 오른쪽 [편집] → 편집 모드: 카드마다 연한 빨강 정사각형 휴지통 버튼, 버튼은 [✓ 완료]로 바뀜
   2) 휴대폰: 카드를 왼쪽으로 밀면 뒤에 숨은 빨간 '삭제' 영역이 드러남 → 누르면 기존 삭제 확인 창
   실제 삭제(확인 창·서버 저장)는 draft.js 의 [data-delete-item] 처리 그대로 사용
   ========================================================= */
(function ($, S) {
  'use strict';
  $(function () {
    var $list = $('#risk-list');
    if (!$list.length) return;
    var OPEN = 88;   // 드러나는 빨간 영역 너비(px)

    /* ---------- 편집 모드 ---------- */
    function setEdit(on) {
      $('#v-list').toggleClass('is-editing', on);
      $('#btn-edit').attr('aria-pressed', on ? 'true' : 'false').toggleClass('btn--primary', on)
        .html(on ? (S.icon ? S.icon('check') : '') + '완료' : '편집');
      $('#draft-editbar').prop('hidden', !on);
      closeAll();
    }
    $('#btn-edit').on('click', function () { setEdit($('#btn-edit').attr('aria-pressed') !== 'true'); });
    $('#v-list').on('safet:hide', function () { setEdit(false); });

    /* ---------- 왼쪽으로 밀어 삭제 ---------- */
    function closeAll(except) {
      $list.find('.risk-item.is-swiped').not(except || []).removeClass('is-swiped')
        .find('.risk-card').css('transform', '');
    }
    var drag = null;
    $list.on('pointerdown', '.risk-item.is-deletable .risk-card', function (e) {
      if (e.pointerType === 'mouse' || $('#v-list').hasClass('is-editing')) return;
      var $li = $(this).closest('.risk-item');
      drag = { $li: $li, $card: $(this), x: e.clientX, y: e.clientY, base: $li.hasClass('is-swiped') ? -OPEN : 0, dx: 0, moving: false, id: e.pointerId };
    });
    $list.on('pointermove', '.risk-card', function (e) {
      if (!drag || e.pointerId !== drag.id) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moving) {
        if (Math.abs(dy) > 10 && Math.abs(dy) > Math.abs(dx)) { drag = null; return; }   // 세로 스크롤
        if (Math.abs(dx) < 8) return;
        drag.moving = true; closeAll(drag.$li);
        drag.$li.addClass('is-dragging');
        try { this.setPointerCapture(e.pointerId); } catch (err) { /* 무시 */ }
      }
      drag.dx = Math.max(-OPEN - 24, Math.min(0, drag.base + dx));
      drag.$card.css('transform', 'translateX(' + drag.dx + 'px)');
    });
    function end() {
      if (!drag) return;
      var d = drag; drag = null;
      d.$li.removeClass('is-dragging');
      if (!d.moving) return;
      var open = d.dx < -OPEN / 2;
      d.$li.toggleClass('is-swiped', open);
      d.$card.css('transform', open ? 'translateX(' + -OPEN + 'px)' : '');
      d.$li.data('swipeEnd', Date.now());
    }
    $list.on('pointerup pointercancel', '.risk-card', end);
    // 민 직후의 '누름'은 상세로 가지 않게, 열린 카드를 누르면 닫기
    $list[0].addEventListener('click', function (e) {
      var li = e.target.closest('.risk-item');
      if (!li || e.target.closest('[data-delete-item]')) return;
      var $li = $(li);
      if (Date.now() - ($li.data('swipeEnd') || 0) < 350 || $li.hasClass('is-swiped')) {
        e.preventDefault(); e.stopImmediatePropagation();
        if ($li.hasClass('is-swiped') && Date.now() - ($li.data('swipeEnd') || 0) >= 350) closeAll();
      }
    }, true);
    $(document).on('pointerdown', function (e) { if (!$(e.target).closest('.risk-item.is-swiped').length) closeAll(); });
    // 다시 그리면(삭제·필터) 편집 모드 표시 유지
    if (window.MutationObserver) new MutationObserver(function () { $list.find('.risk-item__swipe-del').attr('tabindex', '-1'); }).observe($list[0], { childList: true });
  });
})(jQuery, window.SafeT);
