/* =========================================================
   입력 안내 마이크로인터랙션 (UX-003 · 2026-11-21)
   <body data-ux-guide> 인 페이지에서만 동작합니다(검토를 마친 페이지부터 하나씩 적용).
   - 화면이 열리면 비어 있는 첫 필수 칸으로 커서 이동 (data-ux-autofocus="off" 인 화면은 제외)
   - 다음에 채울 필수 칸(또는 선택 묶음)을 .ux-next 로 강조, 다 채우면 주요 버튼을 .ux-ready 로 강조
   - 필수 칸을 채우면 라벨에 ✓ 표시(.ux-done)
   필수 판단: [required] 입력칸 · [data-ux-required] 묶음(안의 radio/checkbox 하나 이상 선택)
   기존 id·name·이벤트·검사(common.js SafeT.validate)는 그대로 둡니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';
  if (!document.body || !document.body.hasAttribute('data-ux-guide')) return;

  function visible(el) { return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length)); }

  function filled(el) {
    var $el = $(el);
    if ($el.is('[data-ux-required]')) return $el.find('input:checked').length > 0;
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked;
    return $.trim($el.val() || '') !== '';
  }

  /** 화면의 필수 항목(문서 순서) */
  function requiredItems($view) {
    return $view.find('input[required], select[required], textarea[required], [data-ux-required]').filter(function () {
      if ($(this).closest('[data-ux-required]').length && !$(this).is('[data-ux-required]')) return false;  // 묶음 안 개별 칸 제외
      if (this.disabled || this.readOnly) return false;
      return visible(this) || $(this).is('[data-ux-required]');
    });
  }

  function labelOf(el) {
    var $el = $(el);
    if ($el.is('[data-ux-required]')) return $el.find('legend, .label').first();
    return el.id ? $('label[for="' + el.id + '"]') : $el.closest('.field').find('.label').first();
  }

  function refresh($view) {
    if (!$view || !$view.length) return;
    var items = requiredItems($view);
    var next = null;
    items.each(function () {
      var ok = filled(this);
      labelOf(this).toggleClass('ux-done', ok);
      if (!ok && !next) next = this;
    });
    $view.find('.ux-next').removeClass('ux-next');
    if (next) $(next).addClass('ux-next');
    // 필수를 다 채우면 화면의 주요 버튼 강조 (필수 항목이 있는 화면만)
    var $primary = $view.find('.bottom-bar .btn--primary, [data-ux-primary]').first();
    $primary.toggleClass('ux-ready', items.length > 0 && !next && !$primary.prop('disabled'));
  }

  function focusFirst($view) {
    if ($view.is('[data-ux-autofocus="off"]')) return;
    var active = document.activeElement;
    if (active && $view[0].contains(active) && $(active).is('input, select, textarea')) return;   // 화면별 처리가 이미 옮김
    var first = requiredItems($view).filter(function () { return !filled(this) && !$(this).is('[data-ux-required]'); }).get(0);
    if (first) first.focus({ preventScroll: false });
  }

  SafeT.uxGuide = { refresh: refresh, focusFirst: focusFirst };

  $(function () {
    // 화면 전환 뒤(데이터를 불러오는 화면은 그린 뒤) 안내
    $(document).on('safet:show', '.view', function () {
      var $v = $(this);
      setTimeout(function () { refresh($v); focusFirst($v); }, 0);
    });
    $(document).on('input change', '.view input, .view select, .view textarea', function () {
      refresh($(this).closest('.view'));
    });
    // 목록을 불러와 새로 그린 경우(필수 묶음 안 선택지가 늦게 생김)에도 다시 계산
    var mo = window.MutationObserver && new MutationObserver(function () { refresh(SafeT.currentView()); });
    if (mo) mo.observe(document.querySelector('.views') || document.body, { childList: true, subtree: true });
    setTimeout(function () { var $v = SafeT.currentView(); refresh($v); focusFirst($v); }, 0);
  });
})(jQuery, window.SafeT);
