/* =========================================================
   내 평가표 (home.html) · H01 · 화면설계서 10쪽
   백엔드 API 와 연결되어 있습니다 (backend/routers/evaluations.py, 로그인 필요).
     GET /evals?tab=&start=&end=&work_no=&page=   평가표 목록 (10개씩)
     GET /workplaces                               사업장 선택 (사용 중인 사업장만)
   - 탭 4개 + 목록 위 기간·사업장 선택 (바꾸면 바로 반영, 선택한 탭은 유지)
   - 같은 평가표가 여러 탭에 나올 수 있음 (05쪽, 36쪽 2번 '임시 처리')
   - 다른 화면에 다녀오면 탭·기간·사업장·스크롤 복원
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var KEY = 'safet.home';
  var STATUS = { W: '작성 중', C: '확정', S: '서명 완료', A: '조치 완료' };
  var state = { tab: 'C', from: '', to: '', work: '', page: 1, scroll: 0 };
  var loadSeq = 0;

  function save() {
    try { window.sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (err) { /* 저장 불가 환경 */ }
  }

  function load() {
    try {
      var s = JSON.parse(window.sessionStorage.getItem(KEY) || 'null');
      if (s) $.extend(state, s);
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

  function card(e) {
    var b = badge(e);
    // 평가표 번호는 주소에 넣지 않고, 누를 때 이 탭에 저장 (SafeT.current · api.js)
    var $li = $('<li class="card eval-card">').attr('data-eval', e.eval_no);
    var $a = $('<a class="eval-card__link">')
      .attr('href', e.eval_status === 'W' ? 'draft.html' : 'result.html')
      .appendTo($li);
    var $head = $('<span class="card__head">').appendTo($a);
    $('<span class="card__title">').text(e.eval_nm || '(이름 없는 평가표)').appendTo($head);
    $('<span class="tag status">').attr('data-status', b).text(STATUS[b]).appendTo($head);
    $('<span class="card__meta">')
      .text([e.workplace || '(사업장 없음)', dot(e.eval_dt), e.eval_writer || ''].filter(Boolean).join(' · '))
      .appendTo($a);

    // 왼쪽 버튼: 작성 중 = 서명하기·확정 후(비활성) / 확정 = 서명하기 n/m / 전원 서명 = 결과 공유
    var $row = $('<div class="btn-row">').appendTo($li);
    if (e.eval_status === 'W') {
      $('<span class="btn" aria-disabled="true">서명하기 · 확정 후</span>').appendTo($row);
    } else if (e.sign_end_dt) {
      $('<a class="btn">결과 공유</a>').attr('href', 'share.html').appendTo($row);
    } else {
      $('<a class="btn">').attr('href', 'sign.html')
        .text(e.member_count ? '서명하기 ' + e.signed_count + '/' + e.member_count : '서명하기')
        .appendTo($row);
    }
    // 오른쪽: 늘 문서 다운로드 (작성 중이면 '미확정' 표시와 함께 · 33쪽)
    $('<button class="btn" type="button">엑셀 다운로드</button>')
      .attr('data-todo', e.eval_status === 'W' ? '미확정 엑셀 다운로드는 API 연결 후 동작해요.' : '엑셀 다운로드는 API 연결 후 동작해요.')
      .appendTo($row);
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
    if (!$('.tabs [data-tab="' + state.tab + '"]').length) state.tab = 'C';
    $('#from_dt').val(state.from);
    $('#to_dt').val(state.to);

    var restoreScroll = state.scroll;
    $.when(loadWorkplaces()).always(function () {
      reload().always(function () {
        if (restoreScroll) window.scrollTo(0, restoreScroll);
      });
    });

    $('.tabs').on('click', '[data-tab]', function (e) {
      e.preventDefault();
      state.tab = $(this).data('tab');
      state.page = 1;
      reload();
    });

    $('#from_dt, #to_dt, #work_no').on('change', function () {
      if (readFilter()) reload();
    });
    $('#home-filter').on('safet:submit', function (e) {
      e.preventDefault();
      if (readFilter()) reload();
    });

    $('#pager').on('click', '[data-page]', function () {
      state.page += +$(this).data('page');
      reload();
      window.scrollTo(0, 0);
    });

    $('#eval-retry').on('click', reload);

    // 카드·서명하기·결과 공유: 이동 전에 '지금 보는 평가표' 번호를 이 탭에 저장 (주소에는 번호 없음)
    $('#eval-list').on('click', 'a[href]', function () {
      SafeT.current.setEval($(this).closest('[data-eval]').attr('data-eval'));
    });

    // 다른 화면으로 갈 때 스크롤 위치 저장
    $(window).on('pagehide', function () {
      state.scroll = window.scrollY;
      save();
    });
  });
})(jQuery, window.SafeT);
