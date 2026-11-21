/* =========================================================
   내 평가표 (home.html) · H01 · 화면설계서 10쪽
   백엔드 API 와 연결되어 있습니다 (backend/routers/evaluations.py, 로그인 필요).
     GET /evals?tab=&start=&end=&work_no=&page=   평가표 목록 (10개씩)
     GET /workplaces                               사업장 선택 (사용 중인 사업장만)
   - 탭(전체·작성 중·확정·서명 완료·조치 완료) + 목록 위 기간·사업장 선택 (바꾸면 바로 반영, 선택한 탭은 유지)
   - 같은 평가표가 여러 탭에 나올 수 있음 (05쪽, 36쪽 2번 '임시 처리')
   - 다른 화면에 다녀오면 탭·기간·사업장·스크롤 복원
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var KEY = 'safet.home';
  var STATUS = { W: '작성 중', C: '확정', S: '서명 완료', A: '조치 완료' };
  var state = { tab: 'ALL', from: '', to: '', work: '', page: 1, scroll: 0 };   // UX-004: 처음 탭 = 전체
  var loadSeq = 0;

  function save() {
    state.day = SafeT.formatDate(SafeT.today());   // 같은 날에만 복원
    try { window.sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (err) { /* 저장 불가 환경 */ }
  }

  function load() {
    try {
      var s = JSON.parse(window.sessionStorage.getItem(KEY) || 'null');
      // UX-014 보완: 저장한 날과 오늘이 다르면 복원하지 않음(어제 종료일이 남아 오늘 평가표가 안 보이던 문제)
      if (s && s.day === SafeT.formatDate(SafeT.today())) $.extend(state, s);
    } catch (err) { /* 무시 */ }
  }

  function isoDate(s) {
    var d = SafeT.parseDate(s);
    if (!d) return null;
    var m = d.getMonth() + 1, day = d.getDate();
    return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
  }

  function dot(iso) {                      // '2026-11-14T10:00:00' → '2026.11.14'
    return iso ? String(iso).slice(0, 10).replace(/-/g, '.') : '';
  }

  /** 카드 상태 표시: 작성 중 → 조치 완료 → 서명 완료 → 확정 순으로 하나 */
  function badge(e) {
    if (e.eval_status === 'W') return 'W';
    if (e.eval_status === 'A') return 'A';
    if (e.sign_end_dt || e.eval_status === 'S') return 'S';
    return 'C';
  }

  /** UX-004 카드 제목 줄이기: 맨 앞 날짜(바로 아래 줄에 다시 나옴)와 모든 카드에 공통인 끝의 '위험성평가'를 뺌.
      화면 표시만 바꾸고 저장된 평가표 이름은 그대로(전체 이름은 title·읽기 프로그램용 이름에 둠) */
  function shortTitle(name) {
    var s = $.trim(name || '');
    var t = s.replace(/^\d{4}[-.]\d{1,2}[-.]\d{1,2}\s*/, '').replace(/\s*위험성\s*평가$/, '');
    return $.trim(t) || s;
  }

  function scroller() { return document.getElementById('home-scroll'); }
  function ico(n) { return SafeT.icon ? SafeT.icon(n) : ''; }

  /** UX-015: 기간 한 칸 표시 'YYYY.MM.DD ~ YYYY.MM.DD' */
  function periodText() {
    $('#period-text').text(($('#from_dt').val() || '처음') + ' ~ ' + ($('#to_dt').val() || '오늘'));
  }
  function togglePeriod(open) {
    $('#period-panel').prop('hidden', !open);
    $('#period-view').attr('aria-expanded', open ? 'true' : 'false');
    if (open) $('#from_dt').trigger('focus');
  }

  function card(e) {
    var b = badge(e);
    // 평가표 번호는 주소에 넣지 않고, 누를 때 이 탭에 저장 (SafeT.current · api.js)
    var $li = $('<li class="card eval-card">').attr('data-eval', e.eval_no);
    var $a = $('<a class="eval-card__link">')
      .attr('href', e.eval_status === 'W' ? 'draft.html' : 'result.html')
      .appendTo($li);
    var $head = $('<span class="card__head">').appendTo($a);
    $('<span class="card__title">').text(e.eval_nm ? shortTitle(e.eval_nm) : '(이름 없는 평가표)').attr('title', e.eval_nm || '').appendTo($head);
    $a.attr('aria-label', (e.eval_nm || '이름 없는 평가표') + ', ' + STATUS[b]);
    $('<span class="tag status">').attr('data-status', b).html(b === 'S' ? ico('check') + STATUS[b] : STATUS[b]).appendTo($head);
    // UX-015: 사업장은 제목과 겹쳐 빼고 '날짜 · 작성자 OOO (· 서명일 MM.DD)'
    var meta = [dot(e.eval_dt), e.eval_writer ? '작성자 ' + e.eval_writer : ''];
    if (b === 'S' && e.sign_end_dt) meta.push('서명일 ' + dot(e.sign_end_dt).slice(5));
    $('<span class="card__meta">').text(meta.filter(Boolean).join(' · ')).attr('title', e.workplace || '').appendTo($a);
    $li.attr('data-card', b);

    // UX-015 상태별 버튼
    //  작성 중 = [이어서 작성하기] 전체 너비 아웃라인
    //  확정    = [서명하기 n/m] 딥그린 + [문서 다운로드] 흰색 아웃라인
    //  서명 완료 = [문서 다운로드] 하나 (결과 공유는 오른쪽 위 작은 링크로 유지 — 08 공유 화면 입구)
    var $row = $('<div class="btn-row">').appendTo($li);
    function dl() {
      return $('<button class="btn" type="button">').html(ico('download') + '문서 다운로드')
        .attr('data-report', e.eval_no)
        .attr('aria-label', (e.eval_nm || '평가표') + (e.eval_status === 'W' ? ' 미확정 문서 다운로드' : ' 문서 다운로드'));
    }
    if (e.eval_status === 'W') {
      $('<a class="btn btn--block eval-card__continue" href="draft.html">').html(ico('pencil') + '이어서 작성하기').appendTo($row);
    } else if (b === 'S' || e.sign_end_dt) {
      dl().addClass('btn--block').appendTo($row);
      $('<a class="eval-card__share" href="share.html">결과 공유 ›</a>').appendTo($li);   // 카드 링크(a) 밖에 둠
    } else {
      $('<a class="btn btn--primary">').attr('href', 'sign.html')
        .html(ico('sign') + (e.member_count ? '서명하기 ' + e.signed_count + '/' + e.member_count : '서명하기'))
        .appendTo($row);
      dl().appendTo($row);
    }
    return $li;
  }

  function render(res) {
    var $list = $('#eval-list').empty();
    $.each(res.items, function (_, e) { $list.append(card(e)); });
    $('#eval-empty').prop('hidden', res.total > 0);

    var pages = Math.max(1, Math.ceil(res.total / res.size));
    var $pager = $('#pager').prop('hidden', res.total <= res.size).empty();
    $('<button class="btn btn--ghost btn--sm" type="button" data-page="-1">이전</button>').prop('disabled', res.page <= 1).appendTo($pager);
    $('<span>').text(res.page + ' / ' + pages).appendTo($pager);
    $('<button class="btn btn--ghost btn--sm" type="button" data-page="1">다음</button>').prop('disabled', res.page >= pages).appendTo($pager);
  }

  function reload() {
    var seq = ++loadSeq;                   // 늦게 온 이전 응답이 화면을 덮지 않게
    $('.tabs [data-tab]').each(function () {
      if ($(this).data('tab') === state.tab) $(this).attr('aria-current', 'page'); else $(this).removeAttr('aria-current');
    });
    $('#eval-error').prop('hidden', true);
    $('#eval-list').attr('aria-busy', 'true');
    save();
    // 빈 값은 보내지 않음 (빈 work_no·날짜는 서버가 형식 오류로 거부)
    var q = { tab: state.tab, page: state.page };
    if (isoDate(state.from)) q.start = isoDate(state.from);
    if (isoDate(state.to)) q.end = isoDate(state.to);
    if (state.work) q.work_no = state.work;
    return SafeT.api.get('/evals?' + $.param(q)).done(function (res) {
      if (seq !== loadSeq) return;
      render(res);
    }).fail(function (err) {
      if (seq !== loadSeq) return;
      $('#eval-list').empty();
      $('#pager, #eval-empty').prop('hidden', true);
      $('#eval-error').prop('hidden', false).find('.js-msg').text(err.message || '평가표 목록을 불러오지 못했어요.');
    }).always(function () {
      if (seq === loadSeq) $('#eval-list').removeAttr('aria-busy');
    });
  }

  /** 기간 검사: 시작일이 종료일보다 늦으면 칸 아래 안내 */
  function readFilter() {
    var $from = $('#from_dt');
    var $to = $('#to_dt');
    SafeT.clearError($from);
    SafeT.clearError($to);
    var f = SafeT.parseDate($from.val());
    var t = SafeT.parseDate($to.val());
    if ($from.val() && !f) { SafeT.fieldError($from, '날짜를 YYYY.MM.DD 형식으로 입력해 주세요.'); return false; }
    if ($to.val() && !t) { SafeT.fieldError($to, '날짜를 YYYY.MM.DD 형식으로 입력해 주세요.'); return false; }
    if (f && t && f > t) { SafeT.fieldError($to, '시작일이 종료일보다 늦어요.'); return false; }
    state.from = f ? SafeT.formatDate(f) : '';
    state.to = t ? SafeT.formatDate(t) : '';
    state.work = $('#work_no').val();
    state.page = 1;
    return true;
  }

  /** 사업장 선택: -전체- + 사용 중인 사업장 (업종 함께 표시) */
  function loadWorkplaces() {
    return SafeT.api.get('/workplaces').done(function (rows) {
      var $sel = $('#work_no').empty().append('<option value="">-전체-</option>');
      $.each(rows, function (_, w) {
        $('<option>').val(w.work_no).text(w.workplace + ' · ' + (w.biz_nm || w.biz_code)).appendTo($sel);
      });
      // 저장해 둔 사업장이 삭제되었으면 전체로
      if (state.work && !$sel.find('option[value="' + state.work + '"]').length) state.work = '';
      $sel.val(state.work);
    });
  }

  $(function () {
    // 처음 값: 시작일 = 이번 달 1일, 종료일 = 오늘(한국 날짜), 사업장 = -전체-
    var today = SafeT.today();
    state.from = SafeT.formatDate(new Date(today.getFullYear(), today.getMonth(), 1));
    state.to = SafeT.formatDate(today);
    load();
    // 저장해 둔 탭이 화면에 없으면(예: 주석 처리한 '조치 완료') 기본 탭으로
    if (!$('.tabs [data-tab="' + state.tab + '"]').length) state.tab = 'ALL';
    $('#from_dt').val(state.from);
    $('#to_dt').val(state.to);

    // 초안에서 평가표를 삭제하고 왔으면 알림 (draft.js · home.html?deleted=1). 새로 고침 때 다시 뜨지 않게 주소에서 지움
    if (new URLSearchParams(location.search).get('deleted')) {
      SafeT.toast('평가표를 휴지통으로 옮겼어요. 30일 안에 휴지통에서 복원할 수 있어요.', 4000);
      try { history.replaceState(null, '', location.pathname + location.hash); } catch (err) { /* 무시 */ }
    }

    var restoreScroll = state.scroll;
    $.when(loadWorkplaces()).always(function () {
      reload().always(function () {
        if (restoreScroll && scroller()) scroller().scrollTop = restoreScroll;   // UX-004: 목록 영역 스크롤 복원
      });
    });

    $('.tabs').on('click', '[data-tab]', function (e) {
      e.preventDefault();
      state.tab = $(this).data('tab');
      state.page = 1;
      if (scroller()) scroller().scrollTop = 0;
      reload();
    });

    $('#from_dt, #to_dt, #work_no').on('change', function () {
      if (readFilter()) reload();
      periodText();
    });
    periodText();
    $('#period-view').on('click', function () { togglePeriod($('#period-panel').prop('hidden')); });
    $('#period-close').on('click', function () { togglePeriod(false); $('#period-view').trigger('focus'); });
    $(document).on('click', function (e) {
      if ($('#period-panel').prop('hidden') || !document.contains(e.target)) return;   // 달력이 다시 그려져 떨어진 요소는 무시
      if (!$(e.target).closest('.period').length && !$(e.target).closest('.mini-cal').length) togglePeriod(false);
    });
    $('#period-panel').on('keydown', function (e) { if (e.key === 'Escape' && !$('.mini-cal').length) { togglePeriod(false); $('#period-view').trigger('focus'); } });
    $('#home-filter').on('safet:submit', function (e) {
      e.preventDefault();
      if (readFilter()) reload();
    });

    $('#pager').on('click', '[data-page]', function () {
      state.page += +$(this).data('page');
      reload();
      if (scroller()) scroller().scrollTop = 0;
    });

    $('#eval-retry').on('click', reload);

    // 카드·서명하기·결과 공유: 이동 전에 '지금 보는 평가표' 번호를 이 탭에 저장 (주소에는 번호 없음)
    $('#eval-list').on('click', 'a[href]', function () {
      SafeT.current.setEval($(this).closest('[data-eval]').attr('data-eval'));
    });

    // 다른 화면으로 갈 때 스크롤 위치 저장
    $(window).on('pagehide', function () {
      state.scroll = scroller() ? scroller().scrollTop : 0;
      save();
    });
  });
})(jQuery, window.SafeT);
