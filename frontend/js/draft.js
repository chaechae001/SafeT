/* =========================================================
   초안 확인 (draft.html)
   S05 리스트 · S05-A 입력 안내 · S05-B 입력 필요 모드 · S06/S06-P/S06-G 위험 상세
   S05-C 일괄 지정 · S07 키워드 추가 · S05-D 저장·확정 중 · S05-E 확정 확인 · C02 삭제
   데이터: 아래 items 는 합성 예시입니다(API 연결 전). 실제 판정이 아닙니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var SIGNAL_TEXT = { R: '즉시 개선', Y: '개선 필요', G: '유지 관리', N: '판단 필요' };

  // 담당자 '등록된 사람' 후보: 작성자·사업장 등록자·기본정보 참여자 (합성 예시)
  var PEOPLE = [
    { name: '김하늘', role: '점장' },
    { name: '박지수', role: '근로자' },
    { name: '이민호', role: '근로자' },
    { name: '정유진', role: '근로자' }
  ];

  var seq = 0;
  function uid() { seq += 1; return 'a' + seq; }

  /** AI 후보 목록 생성. checked: 체크된 위치 배열 */
  function aiList(texts, checked) {
    return $.map(texts, function (t, i) {
      return { id: uid(), text: t, ai: true, checked: $.inArray(i, checked || []) > -1 };
    });
  }

  function makeItem(o) {
    return $.extend({
      job: '', factor: '', type: '', signal: 'N', title: '', desc: '', cause: '', reason: '', law: null,
      curr: [], none: false, plans: [], keep: null, owner: null, due: '',
      judged: true          // eval_dtl.after_judge_yn: 대책이 바뀌면 false → 저장 때 AI 재판단
    }, o);
  }

  /* ---------- 합성 예시 데이터 (eval_dtl · eval_action) ---------- */
  var items = [
    makeItem({
      job: '튀김 조리', factor: '기름 튐', type: '화상', signal: 'R',
      title: '고온 기름 튐에 의한 화상', desc: '뜨거운 기름이 튀어 손과 팔에 닿음',
      cause: '물기 있는 재료 투입 시 기름이 튐 · 바스켓을 꺼낼 때 기름이 손에 떨어짐',
      reason: '170℃ 이상의 기름을 매일 반복 사용하고, 현재 조치가 일부만 있어 화상 가능성과 정도가 높다고 판단했어요.',
      law: { name: '산업안전보건기준에 관한 규칙 [조항명]', summary: '고온 물질 취급 시 보호구 지급·착용 요지', url: 'https://www.law.go.kr/' },
      curr: aiList(['긴 집게를 사용한다', '재료의 물기를 제거한다', '적합한 보호구를 착용한다']),
      plans: aiList(['투입 전 재료 물기 제거', '적합한 손·팔 보호구 착용', '튀김기 주변 비산 방지판 설치'])
    }),
    makeItem({
      job: '바닥 이동', factor: '물기·기름', type: '넘어짐', signal: 'Y',
      title: '젖은 바닥에서 미끄러져 넘어짐', desc: '주방 바닥의 물기·기름에 미끄러짐',
      cause: '튀김기 앞과 개수대 주변에 물기·기름이 남음',
      reason: '바닥 물기가 자주 생기지만 미끄럼 방지 신발을 신고 있어 개선이 필요한 수준으로 판단했어요.',
      curr: aiList(['미끄럼 방지 신발을 신는다', '바닥 물기를 바로 닦는다'], [0]),
      plans: aiList(['미끄럼 방지 매트 설치', '배수구 주변 청소 주기 정하기', '미끄럼 주의 표지 부착'], [0, 1])
    }),
    makeItem({
      job: '칼 보관', factor: '날 접촉', type: '베임', signal: 'G', keep: 'Y',
      title: '칼날 접촉에 의한 베임', desc: '보관 중인 칼을 꺼낼 때 날에 닿음',
      cause: '칼을 꺼내고 넣을 때 손이 날 가까이 감',
      reason: '칼집·칼꽂이 보관과 사용 후 바로 세척하는 조치가 이미 있어 현재 수준을 유지하면 된다고 판단했어요.',
      curr: aiList(['칼집·칼꽂이에 보관한다', '사용 후 바로 세척·보관한다'], [0, 1]),
      plans: aiList(['칼 보관대에 칼날 덮개 사용', '칼 사용 구역 표시', '베임 방지 장갑 비치'])
    }),
    makeItem({
      job: '식자재 운반', factor: '무거운 물건', type: '허리 부담', signal: 'Y',
      title: '무거운 식자재를 들 때 허리 부담', desc: '닭·기름통을 들어 옮길 때 허리에 무리가 감',
      cause: '20kg 이상 상자를 혼자 바닥에서 들어 올림',
      reason: '무거운 물건을 매일 옮기지만 대차를 일부 쓰고 있어 개선이 필요한 수준으로 판단했어요.',
      curr: aiList(['대차를 사용한다', '2인 1조로 든다'], [0]),
      plans: aiList(['운반용 대차 추가 비치', '무거운 식자재 하단 보관', '들기 자세 교육'], [0]),
      owner: { type: 'R', name: '박지수' }, due: '2026.11.28'
    }),
    makeItem({
      job: '냉장고 정리', factor: '바닥 결로', type: '미끄러짐', signal: 'G', keep: 'N',
      title: '냉장고 앞 결로에 미끄러짐', desc: '냉장고 문 앞 바닥에 맺힌 물기에 미끄러짐',
      cause: '문을 자주 여닫아 바닥에 결로가 생김',
      reason: '바닥 매트가 깔려 있어 유지 관리 수준으로 판단했어요.',
      curr: aiList(['바닥 매트를 깔아 둔다', '문을 오래 열어 두지 않는다'], [0]),
      plans: aiList(['냉장고 앞 흡수 매트 교체', '문 고무 패킹 점검', '결로 닦는 시간 정하기'], [0])
    }),
    makeItem({
      job: '가스레인지 사용', factor: '가스 누출', type: '화재', signal: 'N',
      title: '가스 누출에 의한 화재', desc: '밸브를 잠그지 않거나 호스가 낡아 가스가 샘',
      cause: '영업 종료 후 중간 밸브 잠금 여부가 확인되지 않음',
      curr: aiList(['사용 후 중간 밸브를 잠근다', '가스 누출 경보기를 설치해 둔다']),
      // '다시 판단' 데모 결과 (API 연결 전 예시 · 실제 AI 판단 아님)
      demoRejudge: {
        signal: 'Y',
        reason: '(예시 결과) 매일 가스를 쓰고 밸브 잠금 확인이 일정하지 않아 개선이 필요한 수준으로 판단했어요.',
        plans: ['영업 종료 점검표에 밸브 잠금 추가', '가스 호스 교체 주기 정하기', '가스 누출 경보기 작동 점검']
      }
    }),
    makeItem({
      job: '염지 작업', factor: '반복 동작', type: '근골격계 부담', signal: 'Y',
      title: '반복 동작에 의한 손목·어깨 부담', desc: '염지·버무리기를 오래 반복해 손목과 어깨에 부담',
      cause: '한 번에 많은 양을 손으로 버무림',
      reason: '하루 2시간 이상 같은 동작을 반복해 개선이 필요한 수준으로 판단했어요.',
      curr: aiList(['작업 중 쉬는 시간을 둔다', '손목 보호대를 착용한다']),
      plans: aiList(['염지 도구 손잡이 교체', '작업대 높이 조절', '작업 순환 배치'])
    })
  ];

  // 키워드 위험 추가 후보 (S07-C · 합성 예시. API 연결 후 AI 결과로 교체)
  var CANDIDATES = {
    '반죽': [
      { job: '반죽', factor: '회전부', type: '끼임', signal: 'R', title: '반죽기 회전부에 손 끼임', desc: '반죽기가 돌 때 손이 회전부에 들어감',
        cause: '반죽을 떼어 내려고 작동 중에 손을 넣음',
        curr: ['작동을 멈춘 뒤 반죽을 꺼낸다', '덮개를 닫고 작동한다'],
        plans: ['덮개 열림 시 자동 정지 장치 확인', '작동 중 손 넣지 않기 표지 부착', '반죽 긁개 비치'] },
      { job: '반죽', factor: '포대 운반', type: '허리 부담', signal: 'Y', title: '밀가루 포대 운반 중 허리 부담', desc: '20kg 포대를 들어 옮길 때 허리에 무리가 감',
        cause: '포대를 바닥에서 들어 올림',
        curr: ['대차로 옮긴다', '포대를 선반 높이에 둔다'],
        plans: ['포대 보관 선반 높이 조정', '소포장 밀가루로 변경 검토', '들기 자세 교육'] },
      { job: '반죽', factor: '분진', type: '호흡기', signal: 'N', title: '밀가루 분진 흡입', desc: '밀가루를 부을 때 날린 분진을 마심',
        cause: '환기가 약한 곳에서 밀가루를 부음',
        curr: ['마스크를 쓴다'], plans: [] }
    ],
    '배달 포장': [
      { job: '배달 포장', factor: '뜨거운 용기', type: '화상', signal: 'Y', title: '뜨거운 용기에 손 데임', desc: '갓 튀긴 치킨을 담을 때 용기에 손이 닿음',
        cause: '튀긴 직후 맨손으로 포장함',
        curr: ['집게로 담는다'], plans: ['내열 장갑 비치', '포장 전 식힘 칸 마련', '포장대 배치 정리'] },
      { job: '배달 포장', factor: '칼·테이프 커터', type: '베임', signal: 'G', title: '테이프 커터 날에 베임', desc: '포장 테이프를 자를 때 커터 날에 닿음',
        cause: '커터 날 덮개가 없음',
        curr: ['덮개 있는 커터를 쓴다'], plans: ['커터 날 덮개 교체', '커터 보관 위치 정하기', '베임 방지 장갑 비치'] }
    ]
  };

  /* ---------- 규칙 (17쪽: 건수 계산과 확정 검사는 같은 함수) ---------- */
  function checkedCount(list) {
    var n = 0;
    $.each(list, function (_, a) { if (a.checked) n += 1; });
    return n;
  }
  function needsPlan(it) {
    return it.signal === 'R' || it.signal === 'Y' || (it.signal === 'G' && it.keep === 'N');
  }
  /** 빠진 값 목록 (확정 검사 순서): current · signal · plan · owner */
  function missing(it) {
    var m = [];
    if (!it.none && !checkedCount(it.curr)) m.push('current');
    if (it.signal === 'N') m.push('signal');
    if (needsPlan(it) && !checkedCount(it.plans)) m.push('plan');
    if (needsPlan(it) && checkedCount(it.plans) && (!it.owner || !it.due)) m.push('owner');
    return m;
  }
  function has(arr, v) { return $.inArray(v, arr) > -1; }
  function needA(it) { var m = missing(it); return has(m, 'current') || has(m, 'signal') || has(m, 'plan'); }
  function needB(it) { return has(missing(it), 'owner'); }
  /** 후속업무: 빨강·노랑 + 대책을 추가한 초록 (판단 필요 제외) */
  function isFollow(it) { return it.signal !== 'N' && needsPlan(it); }

  function no(i) { return (i < 9 ? '0' : '') + (i + 1); }

  function signalEl(sig) {
    return $('<span class="signal" role="img"><i></i><i></i><i></i></span>')
      .attr('data-signal', sig).attr('aria-label', '위험 신호 ' + SIGNAL_TEXT[sig]);
  }

  var dirty = false;
  function markDirty() { dirty = true; }

  // 로그아웃 확인에서 사용 (api.js)
  SafeT.hasUnsaved = function () { return dirty; };

  /* ---------- S05 리스트 ---------- */
  var filter = 'all';

  function stateText(it) {
    var parts = [];
    var nc = checkedCount(it.curr);
    var np = checkedCount(it.plans);
    if (it.signal === 'N') parts.push('판단 필요');
    parts.push(it.none ? '현재 조치 없음' : (nc ? '현재 조치 ' + nc + '개' : '현재 조치 확인 필요'));
    if (it.signal === 'G' && it.keep !== 'N') {
      parts.push('현재 상태 유지');
    } else if (it.signal !== 'N') {
      if (it.signal === 'G') parts.push('대책 추가');
      parts.push('대책 ' + np + '개');
      if (np) {
        if (it.owner && it.due) parts.push(it.owner.name + ' · ' + SafeT.shortDate(it.due));
        else parts.push(!it.owner ? '담당자 없음' : '예정일 없음');
      }
    }
    return parts.join(' · ');
  }

  function renderList() {
    var $ol = $('#risk-list').empty();
    $.each(items, function (i, it) {
      if (filter === 'follow' && !isFollow(it)) return;
      var need = missing(it).length > 0;
      var $a = $('<a class="card risk-card" href="#v-risk">').attr('data-index', i).toggleClass('card--need', need);
      var $head = $('<span class="card__head">').appendTo($a);
      $('<span class="card__title">').text(no(i) + ' ' + it.job).appendTo($head);
      signalEl(it.signal).appendTo($head);
      $('<span class="card__meta">').text(it.factor + ' · ' + it.type).appendTo($a);
      var $st = $('<span class="risk-card__state">').appendTo($a);
      if (need) $('<span class="tag tag--warn">입력 필요</span>').appendTo($st);
      $st.append(document.createTextNode(' ' + stateText(it)));
      $('<li>').append($a).appendTo($ol);
    });
    if (!$ol.children().length) {
      $('<li class="empty">후속업무 항목이 없어요.</li>').appendTo($ol);
    }
    renderCounts();
  }

  function renderCounts() {
    var a = 0, b = 0, f = 0, touched = false;
    $.each(items, function (_, it) {
      if (needA(it)) a += 1;
      if (needB(it)) b += 1;
      if (isFollow(it)) f += 1;
      if (it.none || checkedCount(it.curr) || checkedCount(it.plans)) touched = true;
    });
    $('#need-a').text(a + '건');
    $('#need-b').text(b + '건');
    $('#need-total, #count-all').text(items.length);
    $('#count-follow').text(f);
    $('#need-row-a').prop('hidden', !a);
    $('#btn-input').prop('hidden', !a).text(touched ? '이어서 입력' : '입력 시작');
    $('#need-row-b').prop('hidden', !b);
    $('#btn-bulk').prop('hidden', !b);
    $('#need-box').prop('hidden', !a && !b);
    $('#done-box').prop('hidden', !!(a || b));
    $('#btn-confirm').toggleClass('btn--emphasis', !a && !b);
  }

  /* ---------- S06 위험 상세 / S05-B 입력 필요 모드 ---------- */
  var state = { index: 0, mode: 'all', needList: [] };

  function cur() { return items[state.index]; }

  function openDetail(index, mode, focus) {
    state.index = index;
    state.mode = mode || 'all';
    SafeT.go('v-risk', { focus: focus || null });
  }

  function renderChecks($list, arr, kind, it) {
    $list.empty();
    $.each(arr, function (_, a) {
      var id = 'chk-' + a.id;
      var $row = a.ai ? $('<label class="check">') : $('<div class="check">');
      var $in = $('<input type="checkbox">').attr({ id: id, 'data-kind': kind, 'data-id': a.id }).prop('checked', a.checked);
      var $txt = a.ai ? $('<span class="check__text">') : $('<label class="check__text">').attr('for', id);
      $txt.text(a.text + ' ').append(
        $('<span class="src">').addClass(a.ai ? 'src--ai' : 'src--manual')
          .text(a.ai ? (kind === 'curr' ? 'AI 후보' : 'AI 추천') : '직접 추가'));
      $row.append($in, $txt);
      if (!a.ai) {
        $('<button class="check__remove" type="button">×</button>')
          .attr({ 'data-remove': a.id, 'data-kind': kind, 'aria-label': a.text + ' 삭제' })
          .appendTo($row);
      }
      $list.append($row);
    });
    if (kind === 'curr') {
      var $n = $('<label class="check">');
      $('<input type="checkbox" data-kind="none" name="curr_none_yn" value="Y">').prop('checked', it.none).appendTo($n);
      $('<span class="check__text">현재 조치 없음</span>').appendTo($n);
      $list.append($n);
    }
  }

  function renderOwner(it) {
    var $v = $('#d-owner-value').empty();
    if (it.owner && it.due) {
      $('<span class="src src--bulk">일괄 지정됨</span>').appendTo($v);
      $('<span class="strong">').text(it.owner.name + ' · ' + it.due).appendTo($v);
      $('#d-owner-btn').text('일괄 지정에서 변경');
    } else {
      $('<span class="strong muted">담당자·예정일 미지정</span>').appendTo($v);
      $('#d-owner-btn').text('일괄 지정에서 지정');
    }
  }

  function navPos() {
    if (state.mode === 'need') {
      var k = $.inArray(state.index, state.needList);
      return {
        prev: k > 0 ? state.needList[k - 1] : null,
        next: k < state.needList.length - 1 ? state.needList[k + 1] : 'end'   // 마지막에서 다음 → 리스트
      };
    }
    return {
      prev: state.index > 0 ? state.index - 1 : null,
      next: state.index < items.length - 1 ? state.index + 1 : null
    };
  }

  function renderDetail() {
    var it = cur();
    if (!it) { state.index = 0; it = cur(); }
    var need = state.mode === 'need';
    var isG = it.signal === 'G';
    var isN = it.signal === 'N';

    if (need) {
      var k = $.inArray(state.index, state.needList);
      $('#d-pos').text('입력 필요 ' + (k + 1) + ' / ' + state.needList.length).addClass('tag tag--warn').removeClass('eyebrow');
      $('#d-mode-link').text('전체 보기').attr('href', '#v-risk');
    } else {
      $('#d-pos').text('위험 ' + (state.index + 1) + ' / ' + items.length).removeClass('tag tag--warn').addClass('eyebrow');
      $('#d-mode-link').text('목록').attr('href', '#v-list');
    }

    $('#d-job').text(it.job);
    $('#d-signal, #d-signal-label').attr('data-signal', it.signal);
    $('#d-signal-text').text(SIGNAL_TEXT[it.signal]);
    $('#d-type').text(it.type);
    $('#d-title').text(it.title);
    $('#d-desc').text(it.desc).prop('hidden', need || !it.desc);
    // 입력 필요 모드: 판단 이유·법령 대신 원인
    $('#d-cause').text(it.cause || '');
    $('#d-cause-box').prop('hidden', !need || !it.cause);
    $('#d-reason').text(it.reason || '');
    $('#d-reason-box').prop('hidden', need || !it.reason);
    if (it.law) {
      $('#d-law-name').text(it.law.name);
      $('#d-law-summary').text(it.law.summary);
      $('#d-law-link').attr('href', it.law.url);
    }
    $('#d-law-box').prop('hidden', need || !it.law);
    $('#d-judge-box').prop('hidden', !isN);

    renderChecks($('#d-curr-list'), it.curr, 'curr', it);

    $('#d-green-switch').prop('hidden', !isG);
    if (isG) $('#d-green-switch input[value="' + (it.keep || 'Y') + '"]').prop('checked', true);
    var showPlan = !isN && (!isG || it.keep === 'N');
    $('#d-keep-note').prop('hidden', !(isG && it.keep !== 'N'));
    $('#d-plan-wait').prop('hidden', !isN);
    $('#d-plan-body').prop('hidden', !showPlan);
    $('#d-plan-req').prop('hidden', !showPlan);
    if (showPlan) {
      renderChecks($('#d-plan-list'), it.plans, 'plan', it);
      renderOwner(it);
    }

    var pos = navPos();
    $('#d-prev').prop('disabled', pos.prev === null);
    $('#d-next').prop('disabled', pos.next === null);

    $('#risk-form .inline-add').remove();
    $('#risk-form .section').removeClass('is-invalid');
    SafeT.clearErrors($('#v-risk'));
  }

  // 확정 시 빠진 값: 해당 필드로 이동해 그 자리에서 안내 (결정 13)
  var MISSING_MSG = {
    current: "현재 안전조치를 선택하거나 '현재 조치 없음'을 체크해 주세요.",
    signal: 'AI 판단이 필요한 항목이에요. 다시 판단한 뒤 확정할 수 있어요.',
    plan: '개선대책을 1개 이상 선택해 주세요.',
    owner: '담당자·예정일을 일괄 지정에서 넣어 주세요.'
  };

  function focusMissing(field) {
    var $msg = $('<p class="error-text js-error" role="alert">').text(MISSING_MSG[field]);
    var $focus;
    if (field === 'current') {
      $('#d-current').addClass('is-invalid');
      $('#d-curr-list').before($msg);
      $focus = $('#d-curr-list input').first();
    } else if (field === 'signal') {
      $('#d-judge-box').append($msg);
      $focus = $('#d-rejudge');
    } else if (field === 'plan') {
      $('#d-plan').addClass('is-invalid');
      $('#d-plan-list').before($msg);
      $focus = $('#d-plan-list input').first();
    } else {
      $('#d-owner').after($msg);
      $focus = $('#d-owner-btn');
    }
    var el = $msg.get(0);
    el.scrollIntoView({ block: 'center', behavior: SafeT.reduceMotion ? 'auto' : 'smooth' });
    if ($focus.length) $focus.get(0).focus({ preventScroll: true });
  }

  /* ---------- 직접 추가 ---------- */
  function normalize(s) { return $.trim(s).replace(/\s+/g, ' '); }

  function addCustom(kind, $input) {
    var it = cur();
    var list = kind === 'curr' ? it.curr : it.plans;
    var text = normalize($input.val());
    SafeT.clearError($input);
    if (!text) {
      SafeT.fieldError($input, '내용을 입력해 주세요.');
      $input.trigger('focus');
      return;
    }
    var dup = false;
    $.each(list, function (_, a) { if (normalize(a.text) === text) dup = true; });
    if (dup) {
      SafeT.fieldError($input, '이미 있는 항목이에요.');
      $input.trigger('focus');
      return;
    }
    list.push({ id: uid(), text: text, ai: false, checked: true });   // 추가한 항목은 체크된 상태
    if (kind === 'curr') it.none = false;
    if (kind === 'plan') it.judged = false;
    markDirty();
    renderDetail();
    renderCounts();
    $('#' + (kind === 'curr' ? 'd-curr-list' : 'd-plan-list') + ' input[data-kind="' + kind + '"]').last().trigger('focus');
  }

  /* ---------- S05-C 일괄 지정 ---------- */
  var bulk = { only: null, back: 'v-list', open: false };

  function bulkTargets() {
    var t = [];
    $.each(items, function (i, it) { if (isFollow(it)) t.push(i); });
    return t;
  }

  function updateBulkCount() {
    var total = $('#bulk-list input').length;
    var n = $('#bulk-list input:checked').length;
    $('.js-bulk-count').text(n);
    $('#bulk-all').prop('checked', n > 0 && n === total).prop('indeterminate', n > 0 && n < total);
    $('#bulk-open').prop('disabled', !n);
  }

  function renderBulk() {
    var $list = $('#bulk-list').empty();
    var t = bulkTargets();
    $.each(t, function (_, i) {
      var it = items[i];
      var $l = $('<label class="check bulk__item">');
      $('<input type="checkbox" name="eval_dtl_no">').val(i).prop('checked', bulk.only === null || bulk.only === i).appendTo($l);
      var $tx = $('<span class="check__text">').appendTo($l);
      $('<span class="strong">').text(no(i) + ' ' + it.job).appendTo($tx);
      $tx.append('<br>');
      $('<span class="check__meta">').text(it.factor + ' · ' + it.type + (it.signal === 'G' ? ' · 대책 추가' : '')).appendTo($tx);
      $tx.append('<br>');
      var $m = $('<span class="check__meta">').appendTo($tx);
      if (it.owner && it.due) {
        $m.text(it.owner.name + ' · ' + SafeT.shortDate(it.due) + ' ');
        $('<span class="src src--bulk">입력됨</span>').appendTo($m);
      } else {
        $m.text('담당자·예정일 없음');
      }
      signalEl(it.signal).appendTo($l);
      $list.append($l);
    });
    $('#bulk-total').text(t.length);
    $('#bulk-cancel').attr('href', '#' + bulk.back);
    updateBulkCount();
  }

  function openAssign() {
    if (!$('#bulk-list input:checked').length) {
      SafeT.toast('지정할 항목을 선택해 주세요.');
      return;
    }
    // 기본값 없이 사용자가 직접 입력 (결정 6)
    var $people = $('#assign-people').empty();
    $.each(PEOPLE, function (i, p) {
      var $l = $('<label class="check">');
      $('<input type="radio" name="manager_nm">').val(p.name).appendTo($l);
      $('<span class="check__text">').text(p.name + ' ').append($('<span class="muted">').text('· ' + p.role)).appendTo($l);
      $people.append($l);
    });
    $('#assign-form input[name="manager_type"][value="R"]').prop('checked', true);
    $('#manager_nm_manual, #due_dt').val('');
    SafeT.clearErrors($('#assign-form'));
    $('#assign-people').removeClass('is-invalid');
    SafeT.openModal('assign');
  }

  /* ---------- S05-D 저장·확정 중 ---------- */
  var cancelProgress = null;

  var PROGRESS = {
    save: {
      title: '평가표를 저장하고 있어요',
      steps: [
        { pct: 30, step: '저장', label: '평가표를 저장하고 있어요' },
        { pct: 70, step: '예상 신호 판단', label: '개선 후 예상 신호를 판단하고 있어요' },
        { pct: 100, step: '완료', label: '저장했어요' }
      ]
    },
    confirm: {
      title: '평가표를 확정하고 있어요',
      steps: [
        { pct: 50, step: '남은 예상 신호 판단', label: '남은 예상 신호를 판단하고 있어요' },
        { pct: 80, step: '후속업무 집계', label: '후속업무를 모으고 있어요' },
        { pct: 100, step: '확정 처리', label: '평가표를 확정했어요' }
      ]
    },
    add: {
      title: '위험 항목을 추가하고 있어요',
      steps: [
        { pct: 25, step: '위험 후보 분석', label: '위험 후보를 분석하고 있어요' },
        { pct: 50, step: '신호 판단', label: '위험 신호를 판단하고 있어요' },
        { pct: 80, step: '대책·현재 조치 후보', label: '대책과 현재 조치 후보를 만들고 있어요' },
        { pct: 100, step: '완료', label: '추가했어요' }
      ]
    }
  };

  /** 평가표 저장: 대책이 바뀐 항목이 있으면 AI 판단(진행률), 없으면 데이터만 저장(원형 로딩) */
  function saveDraft(back) {
    var needJudge = false;
    $.each(items, function (_, it) { if (!it.judged && it.signal !== 'N') needJudge = true; });
    if (needJudge) {
      SafeT.go('v-saving', { kind: 'save', back: back });
      return $.Deferred().resolve().promise();
    }
    SafeT.loading(true);
    return SafeT.wait(500).then(function () {
      SafeT.loading(false);
      dirty = false;
      SafeT.toast('저장했어요');
    });
  }

  var pendingAdd = [];

  function finishProgress(o) {
    if (o.kind === 'save') {
      $.each(items, function (_, it) { it.judged = true; });
      dirty = false;
      SafeT.go(o.back || 'v-list', o.back === 'v-risk' ? { focus: null } : null);
      SafeT.toast('저장했어요');
    } else if (o.kind === 'confirm') {
      dirty = false;
      window.location.href = 'result.html';
    } else if (o.kind === 'add') {
      $.each(pendingAdd, function (_, c) {
        items.push(makeItem({
          job: c.job, factor: c.factor, type: c.type, signal: c.signal, title: c.title, desc: c.desc, cause: c.cause,
          curr: aiList(c.curr),                                   // 현재 조치 미선택
          plans: (c.signal === 'R' || c.signal === 'Y' || c.signal === 'G') ? aiList(c.plans) : [],
          keep: c.signal === 'G' ? 'Y' : null
        }));
      });
      var n = pendingAdd.length;
      pendingAdd = [];
      filter = 'all';
      SafeT.go('v-list');
      SafeT.toast(n + '건을 추가했어요');
    }
  }

  /* ---------- 로그인 만료 시 편집 내용 보관 · 다시 로그인하면 복구 (설계서 07쪽) ---------- */
  if (SafeT.auth) {
    SafeT.auth.onExpire(function () {
      if (!dirty) return null;
      return { page: 'draft', data: { items: items, state: state, filter: filter } };
    });
  }

  function restoreAfterLogin() {
    var r = SafeT.auth && SafeT.auth.takeRestore('draft');
    if (!r || !$.isArray(r.items)) return false;
    items = $.map(r.items, function (it) { return makeItem(it); });
    state = $.extend({ index: 0, mode: 'all', needList: [] }, r.state);
    filter = r.filter || 'all';
    // 직접 추가 항목 id 가 겹치지 않도록 번호 이어서
    $.each(items, function (_, it) {
      $.each(it.curr.concat(it.plans), function (_, a) {
        var n = parseInt(String(a.id).slice(1), 10);
        if (n > seq) seq = n;
      });
    });
    dirty = true;
    return true;
  }

  /* ---------- 이벤트 ---------- */
  $(function () {
    var restored = restoreAfterLogin();
    renderList();
    if (restored) {
      $('#v-list .tabs [data-filter]').removeAttr('aria-current').filter('[data-filter="' + filter + '"]').attr('aria-current', 'page');
      if ($('#v-risk').hasClass('is-active')) renderDetail();
      SafeT.toast('다시 로그인해서 보던 화면과 수정 내용을 되살렸어요. 저장해 주세요.');
    }

    // 리스트
    $('#v-list').on('safet:show', renderList);

    $('#risk-list').on('click', 'a[data-index]', function (e) {
      e.preventDefault();
      openDetail(+$(this).attr('data-index'), 'all');
    });

    $('#v-list .tabs').on('click', '[data-filter]', function (e) {
      e.preventDefault();
      filter = $(this).data('filter');
      $('#v-list .tabs [data-filter]').removeAttr('aria-current');
      $(this).attr('aria-current', 'page');
      renderList();
    });

    // 입력 시작 / 이어서 입력: 입력 필요 항목만 이동
    $('#btn-input').on('click', function () {
      state.needList = [];
      $.each(items, function (i, it) { if (needA(it)) state.needList.push(i); });
      if (state.needList.length) openDetail(state.needList[0], 'need');
    });

    $('#btn-bulk').on('click', function () {
      SafeT.go('v-bulk', { only: null, back: 'v-list' });
    });

    $('#btn-save').on('click', function (e) {
      e.preventDefault();
      saveDraft('v-list');
    });

    $('#btn-confirm').on('click', function (e) {
      e.preventDefault();
      SafeT.openModal('confirm');
    });

    // 확인 창이 열릴 때 필수값 검사 (주소로 열어도 동일). 빠진 값이 있으면 창 대신 해당 필드로
    $('#confirm').on('safet:open', function () {
      for (var i = 0; i < items.length; i += 1) {
        var m = missing(items[i]);
        if (m.length) {
          SafeT.closeModal(true);
          openDetail(i, 'all', m[0]);
          return;
        }
      }
      $('#btn-confirm-ok').prop('disabled', false);
    });

    $('#btn-confirm-ok').on('click', function () {
      $(this).prop('disabled', true);              // 중복 클릭 방지
      SafeT.go('v-saving', { kind: 'confirm' });
    });

    // 위험 상세
    $('#v-risk').on('safet:show', function (e, o) {
      renderDetail();
      if (o && o.focus) focusMissing(o.focus);
    });

    $('#d-mode-link').on('click', function (e) {
      if (state.mode === 'need') {               // 전체 보기: 원래처럼 전체 항목 이동
        e.preventDefault();
        state.mode = 'all';
        renderDetail();
      }
    });

    $('#d-prev').on('click', function () {
      var p = navPos().prev;
      if (p === null) return;
      state.index = p;
      renderDetail();
      window.scrollTo(0, 0);
    });

    $('#d-next').on('click', function () {
      var n = navPos().next;
      if (n === 'end') { SafeT.go('v-list'); return; }
      if (n === null) return;
      state.index = n;
      renderDetail();
      window.scrollTo(0, 0);
    });

    $('#d-save').on('click', function () { saveDraft('v-risk'); });

    // 다시 판단: API 연결 전에는 데모 결과로 채움 (예시 결과임을 판단 이유에 표시)
    $('#d-rejudge').on('click', function () {
      var it = cur();
      if (!it.demoRejudge) { SafeT.toast('다시 판단은 API 연결 후 동작해요.'); return; }
      var $btn = $(this).prop('disabled', true);
      SafeT.loading(true);
      SafeT.wait(800).then(function () {
        it.signal = it.demoRejudge.signal;
        it.reason = it.demoRejudge.reason;
        it.plans = aiList(it.demoRejudge.plans);          // 추천 대책은 미체크로 시작
        it.judged = true;
        delete it.demoRejudge;
        markDirty();
        SafeT.loading(false);
        $btn.prop('disabled', false);
        renderDetail();
        renderCounts();
        SafeT.toast('다시 판단했어요. (API 연결 전 예시 결과)');
      });
    });

    // 체크 변경 (현재 조치 · 현재 조치 없음 · 개선대책)
    $('#risk-form').on('change', 'input[data-kind]', function () {
      var it = cur();
      var kind = $(this).data('kind');
      var on = this.checked;
      if (kind === 'none') {
        it.none = on;
        if (on) {                                    // '없음'과 다른 후보는 함께 선택 불가
          $.each(it.curr, function (_, a) { a.checked = false; });
          $('#d-curr-list input[data-kind="curr"]').prop('checked', false);
        }
      } else {
        var list = kind === 'curr' ? it.curr : it.plans;
        var id = $(this).data('id');
        $.each(list, function (_, a) { if (a.id === id) a.checked = on; });
        if (kind === 'curr' && on && it.none) {
          it.none = false;
          $('#d-curr-list input[data-kind="none"]').prop('checked', false);
        }
        if (kind === 'plan') it.judged = false;
      }
      markDirty();
      $(this).closest('.section').removeClass('is-invalid').find('.js-error').remove();
      renderCounts();
    });

    // 초록 항목: 현재 상태 유지 / 대책 추가
    $('#d-green-switch').on('change', 'input', function () {
      var it = cur();
      var v = this.value;
      if (v === 'Y' && it.keep === 'N' && (checkedCount(it.plans) || it.owner || it.due)) {
        SafeT.confirm({
          title: '현재 상태 유지로 바꿀까요?',
          message: '선택한 대책이 지워져요. 일괄 지정으로 넣은 담당자·예정일도 함께 지워져요.',
          ok: '바꾸기',
          cancel: '취소'
        }).then(function (yes) {
          if (yes) {
            it.plans = $.grep(it.plans, function (a) { return a.ai; });
            $.each(it.plans, function (_, a) { a.checked = false; });
            it.owner = null;
            it.due = '';
            it.keep = 'Y';
            it.judged = false;
            markDirty();
          }
          renderDetail();
          renderCounts();
        });
        return;
      }
      it.keep = v;
      markDirty();
      renderDetail();
      renderCounts();
    });

    // 직접 추가
    $('#risk-form').on('click', '[data-add]', function () {
      var $btn = $(this);
      var kind = $btn.data('add');
      var $exist = $btn.next('.inline-add');
      if ($exist.length) { $exist.find('input').trigger('focus'); return; }
      var $row = $('<div class="inline-add">');
      var $ir = $('<div class="input-row">').appendTo($row);
      var label = kind === 'curr' ? '추가할 안전조치' : '추가할 개선대책';
      var $in = $('<input class="input" maxlength="500">')
        .attr({ placeholder: kind === 'curr' ? '매장에서 하고 있는 조치 입력' : '개선대책 입력', 'aria-label': label })
        .appendTo($ir);
      var $ok = $('<button class="btn" type="button">추가</button>').appendTo($ir);
      $row.insertAfter($btn);
      $in.trigger('focus');
      $ok.on('click', function () { addCustom(kind, $in); });
      $in.on('keydown', function (e) {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); addCustom(kind, $in); }
        if (e.key === 'Escape') { e.stopPropagation(); $row.remove(); $btn.trigger('focus'); }
      });
    });

    // 직접 추가 항목 삭제 (ai_yn='N'만)
    $('#risk-form').on('click', '[data-remove]', function () {
      var it = cur();
      var kind = $(this).data('kind');
      var id = $(this).data('remove');
      if (kind === 'curr') it.curr = $.grep(it.curr, function (a) { return a.id !== id; });
      else { it.plans = $.grep(it.plans, function (a) { return a.id !== id; }); it.judged = false; }
      markDirty();
      renderDetail();
      renderCounts();
    });

    // 일괄 지정에서 변경: 이 항목만 선택된 상태로 일괄 지정 창
    $('#d-owner-btn').on('click', function () {
      SafeT.go('v-bulk', { only: state.index, back: 'v-risk', open: true });
    });

    // 일괄 지정
    $('#v-bulk').on('safet:show', function (e, o) {
      if (o && o.only !== undefined) bulk = { only: o.only, back: o.back || 'v-list', open: !!o.open };
      renderBulk();
      if (bulk.open) { bulk.open = false; openAssign(); }
    });

    $('#bulk-all').on('change', function () {
      $('#bulk-list input').prop('checked', this.checked);
      updateBulkCount();
    });
    $('#bulk-list').on('change', 'input', updateBulkCount);
    $('#bulk-open').on('click', openAssign);

    $('#assign-form').on('safet:validate', function (e) {
      var type = $('#assign-form input[name="manager_type"]:checked').val();
      if (type === 'R' && !$('#assign-people input:checked').length) {
        e.preventDefault();
        var $first = $('#assign-people input').first();
        $first.addClass('is-invalid');
        $('#assign-people').addClass('is-invalid')
          .after('<p class="error-text js-error" role="alert">담당자를 선택해 주세요.</p>');
      }
      if (type === 'D' && !normalize($('#manager_nm_manual').val())) {
        e.preventDefault();
        SafeT.fieldError($('#manager_nm_manual'), '담당자 이름을 입력해 주세요.');
      }
    });
    $('#assign-people').on('change', 'input', function () {
      $('#assign-people').removeClass('is-invalid').next('.js-error').remove();
      $('#assign-people .is-invalid').removeClass('is-invalid');
    });

    $('#assign-form').on('safet:submit', function (e) {
      e.preventDefault();
      var type = $('#assign-form input[name="manager_type"]:checked').val();
      // 켜진 모드의 값만 저장
      var name = type === 'R' ? $('#assign-people input:checked').val() : normalize($('#manager_nm_manual').val());
      var due = SafeT.formatDate(SafeT.parseDate($('#due_dt').val()));
      var targets = $('#bulk-list input:checked').map(function () { return +this.value; }).get();
      SafeT.loading(true);                         // AI 판단 없이 데이터만 저장: 원형 로딩만
      SafeT.wait(500).then(function () {
        $.each(targets, function (_, i) {           // 선택한 항목은 모두 덮어쓰기
          items[i].owner = { type: type, name: name };
          items[i].due = due;
        });
        markDirty();
        SafeT.loading(false);
        SafeT.toast(targets.length + '건에 적용했어요');
        SafeT.go(bulk.back, bulk.back === 'v-risk' ? { focus: null } : null);
      });
    });

    // 키워드로 위험 추가
    $('#add-form').on('safet:submit', function (e) {
      e.preventDefault();
      var kw = normalize($('#keyword').val());
      var found = [];
      $.each(CANDIDATES, function (key, list) {
        if (kw.indexOf(key) > -1 || key.indexOf(kw) > -1) found = found.concat(list);
      });
      // 이미 있는 작업·위험 조합은 후보에서 제외
      found = $.grep(found, function (c) {
        var dup = false;
        $.each(items, function (_, it) { if (it.job === c.job && it.title === c.title) dup = true; });
        return !dup;
      });
      $('#add-keyword').text(kw);
      var $box = $('#add-candidates');
      $box.children('label').remove();
      $.each(found, function (i, c) {
        var $l = $('<label class="check">').data('candidate', c);
        $('<input type="checkbox" name="candidate">').val(i).appendTo($l);
        $('<span class="check__text">').text(c.title + ' ').append('<span class="src src--ai">AI 후보</span>').appendTo($l);
        $box.append($l);
      });
      $('#add-empty').prop('hidden', found.length > 0);
      SafeT.go('v-add-select');
    });

    $('#v-add-select').on('safet:show', function () {
      if (!$('#add-candidates label').length && $('#add-empty').prop('hidden')) SafeT.go('v-add');
    });

    $('#select-form').on('safet:validate', function (e) {
      if (!$('#add-candidates input:checked').length) {
        e.preventDefault();
        var $first = $('#add-candidates input').first();
        if ($first.length) SafeT.fieldError($first, '추가할 위험을 하나 이상 선택해 주세요.');
        else SafeT.toast('추가할 후보가 없어요. 다른 키워드로 찾아 주세요.');
      }
    });

    $('#select-form').on('safet:submit', function (e) {
      e.preventDefault();
      pendingAdd = $('#add-candidates input:checked').map(function () {
        return $(this).closest('label').data('candidate');
      }).get();
      $('#keyword').val('');
      SafeT.go('v-saving', { kind: 'add' });
    });

    // 저장·확정 중
    $('#v-saving')
      .on('safet:show', function (e, o) {
        if (!o || !PROGRESS[o.kind]) { SafeT.go('v-list'); return; }
        if (cancelProgress) cancelProgress();
        cancelProgress = SafeT.runProgress($(this), {
          title: PROGRESS[o.kind].title,
          steps: PROGRESS[o.kind].steps,
          done: function () { cancelProgress = null; finishProgress(o); }
        });
      })
      .on('safet:hide', function () {
        if (cancelProgress) cancelProgress();
        cancelProgress = null;
      });

    // 저장하지 않은 변경이 있을 때 다른 화면(홈·다른 평가표)으로 나가면 묻기
    $(document).on('click', 'a[href$=".html"], a[href*=".html#"]', function (e) {
      if (!dirty || $(this).closest('#delete').length) return;
      var href = $(this).attr('href');
      e.preventDefault();
      $('details.menu[open]').prop('open', false);
      SafeT.confirm({
        title: '저장하지 않은 변경이 있어요',
        message: '평가표를 저장하고 나갈까요?',
        ok: '저장',
        alt: '나가기',
        cancel: '계속 작성'
      }).then(function (a) {
        if (a === 'alt') { dirty = false; window.location.href = href; }
        if (a === true) {
          SafeT.loading(true);
          SafeT.wait(500).then(function () { dirty = false; window.location.href = href; });
        }
      });
    });
  });
})(jQuery, window.SafeT);
