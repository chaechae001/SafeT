/* =========================================================
   내 평가표 (home.html) · H01
   - 탭 4개 + 목록 위 기간·사업장 선택 (바꾸면 바로 반영, 선택한 탭은 유지)
   - 한 평가표가 여러 탭에 나타날 수 있음 (확정이면서 서명 완료 등 · 36쪽 확인 필요)
   - 목록 10개씩, 다른 화면에 다녀오면 탭·기간·사업장·스크롤 복원
   평가표 목록은 합성 예시입니다(API 연결 전).
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  // eval_mst + 서명 현황 · 합성 예시
  var EVALS = [
    { no: 101, name: '11월 주방 위험성평가', work: 1, workName: '온기치킨 성수점', date: '2026.11.14', writer: '김하늘', status: 'C', signed: 1, signNeed: 3, actionDone: false },
    { no: 102, name: '11월 홀 위험성평가', work: 2, workName: '온기분식', date: '2026.11.03', writer: '박지수', status: 'C', signed: 2, signNeed: 2, actionDone: false },
    { no: 103, name: '11월 창고 위험성평가', work: 2, workName: '온기분식', date: '2026.11.10', writer: '박지수', status: 'W', signed: 0, signNeed: 2, actionDone: false },
    { no: 104, name: '11월 배달 포장 위험성평가', work: 1, workName: '온기치킨 성수점', date: '2026.11.05', writer: '김하늘', status: 'C', signed: 3, signNeed: 3, actionDone: true },
    { no: 105, name: '10월 주방 위험성평가', work: 1, workName: '온기치킨 성수점', date: '2026.10.14', writer: '김하늘', status: 'C', signed: 3, signNeed: 3, actionDone: true }
  ];
  var PAGE_SIZE = 10;
  var KEY = 'safet.home';

  var state = { tab: 'C', from: '', to: '', work: '', page: 1, scroll: 0 };

  function allSigned(e) { return e.status === 'C' && e.signed >= e.signNeed; }

  function inTab(e, tab) {
    if (tab === 'W') return e.status === 'W';
    if (tab === 'C') return e.status === 'C';
    if (tab === 'S') return allSigned(e);
    if (tab === 'A') return e.status === 'C' && e.actionDone;
    return true;
  }

  function badge(e) {
    if (e.status === 'W') return { code: 'W', text: '작성 중' };
    if (e.actionDone) return { code: 'A', text: '조치 완료' };
    if (allSigned(e)) return { code: 'S', text: '서명 완료' };
    return { code: 'C', text: '확정' };
  }

  function save() {
    try { window.sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (err) { /* 저장 불가 환경 */ }
  }

  function load() {
    try {
      var s = JSON.parse(window.sessionStorage.getItem(KEY) || 'null');
      if (s) $.extend(state, s);
    } catch (err) { /* 무시 */ }
  }

  function render() {
    var from = SafeT.parseDate(state.from);
    var to = SafeT.parseDate(state.to);
    var rows = $.grep(EVALS, function (e) {
      var d = SafeT.parseDate(e.date);
      return inTab(e, state.tab) &&
        (!state.work || String(e.work) === String(state.work)) &&
        (!from || d >= from) && (!to || d <= to);
    });
    rows.sort(function (a, b) { return SafeT.parseDate(b.date) - SafeT.parseDate(a.date); });

    var pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (state.page > pages) state.page = pages;
    var view = rows.slice((state.page - 1) * PAGE_SIZE, state.page * PAGE_SIZE);

    var $list = $('#eval-list').empty();
    $.each(view, function (_, e) {
      var b = badge(e);
      var $li = $('<li class="card eval-card">');
      var $a = $('<a class="eval-card__link">').attr('href', e.status === 'W' ? 'draft.html' : 'result.html').appendTo($li);
      var $head = $('<span class="card__head">').appendTo($a);
      $('<span class="card__title">').text(e.name).appendTo($head);
      $('<span class="tag status">').attr('data-status', b.code).text(b.text).appendTo($head);
      $('<span class="card__meta">').text(e.workName + ' · ' + e.date + ' · ' + e.writer).appendTo($a);

      var $row = $('<div class="btn-row">').appendTo($li);
      if (e.status === 'W') {
        $('<span class="btn" aria-disabled="true">서명하기 · 확정 후</span>').appendTo($row);
      } else if (allSigned(e)) {
        $('<a class="btn" href="share.html">결과 공유</a>').appendTo($row);
      } else {
        $('<a class="btn" href="sign.html">').text('서명하기 ' + e.signed + '/' + e.signNeed).appendTo($row);
      }
      $('<button class="btn" type="button" data-excel>엑셀 다운로드</button>')
        .attr('data-draft', e.status === 'W' ? '1' : '').appendTo($row);
      $list.append($li);
    });

    $('#eval-empty').prop('hidden', rows.length > 0);
    var $pager = $('#pager').prop('hidden', rows.length <= PAGE_SIZE).empty();
    $('<button class="btn btn--ghost btn--sm" type="button" data-page="-1">이전</button>').prop('disabled', state.page <= 1).appendTo($pager);
    $('<span>').text(state.page + ' / ' + pages).appendTo($pager);
    $('<button class="btn btn--ghost btn--sm" type="button" data-page="1">다음</button>').prop('disabled', state.page >= pages).appendTo($pager);

    $('.tabs [data-tab]').each(function () {
      if ($(this).data('tab') === state.tab) $(this).attr('aria-current', 'page'); else $(this).removeAttr('aria-current');
    });
    save();
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

  $(function () {
    // 처음 값: 시작일 = 이번 달 1일, 종료일 = 오늘(한국 날짜), 사업장 = -전체-
    var today = SafeT.today();
    state.from = SafeT.formatDate(new Date(today.getFullYear(), today.getMonth(), 1));
    state.to = SafeT.formatDate(today);
    load();

    $('#from_dt').val(state.from);
    $('#to_dt').val(state.to);
    $('#work_no').val(state.work);
    render();
    if (state.scroll) window.scrollTo(0, state.scroll);

    $('.tabs').on('click', '[data-tab]', function (e) {
      e.preventDefault();
      state.tab = $(this).data('tab');
      state.page = 1;
      render();
    });

    $('#from_dt, #to_dt, #work_no').on('change', function () {
      if (readFilter()) render();
    });
    $('#home-filter').on('safet:submit', function (e) {
      e.preventDefault();
      if (readFilter()) render();
    });

    $('#pager').on('click', '[data-page]', function () {
      state.page += +$(this).data('page');
      render();
      window.scrollTo(0, 0);
    });

    // 엑셀 다운로드: 작성 중이면 '미확정' 표시와 함께 (API 연결 후 파일 생성)
    $('#eval-list').on('click', '[data-excel]', function () {
      SafeT.toast($(this).attr('data-draft') ? '미확정 엑셀은 API 연결 후 내려받을 수 있어요.' : '엑셀 다운로드는 API 연결 후 동작해요.');
    });

    // 다른 화면으로 갈 때 스크롤 위치 저장
    $(window).on('pagehide', function () {
      state.scroll = window.scrollY;
      save();
    });
  });
})(jQuery, window.SafeT);
