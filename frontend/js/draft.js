/* =========================================================
   초안 확인 (draft.html)
   S05 리스트 · S05-A 입력 안내 · S05-B 입력 필요 모드 · S06/S06-P/S06-G 위험 상세
   S05-C 일괄 지정 · S07 키워드 추가 · S05-D 저장·확정 중 · S05-E 확정 확인 · C02 삭제
   데이터: 서버의 eval_no별 저장값. 실제 모델 미연결 시 N, 명시적 demo 모드만 합성 신호.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var SIGNAL_TEXT = { R: '상 · 개선 필요', Y: '중 · 개선 필요', G: '하 · 유지 관리', N: '판단 필요' };

  var PEOPLE = [];

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
      judged: true          // eval_dtl.after_judge_yn: 대책이 바뀌면 false → 저장 때 예상 위험도 재계산
    }, o);
  }

  var items = [];
  var evaluation = null, busy = false;
  var evalNo = Number(new URLSearchParams(location.search).get('eval')) || (SafeT.current && SafeT.current.evalNo());
  if(evalNo && SafeT.current)SafeT.current.setEval(evalNo);
  function applyDocument(doc) {
    evaluation = doc;
    items = doc.items.map(makeItem);
    PEOPLE = [doc.eval_writer].concat(doc.members).filter(function(n,i,a){return a.indexOf(n)===i;}).map(function(n){return {name:n,role:'참여자'};});
    $('#v-list h1').first().text(doc.eval_nm);
    $('#d-reason-box .src').text(doc.generation_source==='demo'?'시험용 고정 신호':'판단 대기');
    $('.disclaimer').text(doc.generation_source==='demo' ? '개발 시험용 합성 평가표 · 실제 현장 판정에 사용하지 마세요.' : '실제 위험 판단 모델 미연결 · 판단 필요 항목은 확정할 수 없습니다.');
    if(['catalog_v1','catalog_ai_v1'].indexOf(doc.generation_source)!==-1){ $('.disclaimer').text('선택한 조치를 기준으로 계산한 위험도입니다.');$('#d-reason-box .src').text('DB 기준'); }
    if(SafeT.catalogAI)SafeT.catalogAI.summary(doc,submitAnswers);
    renderList();
  }
  function submitAnswers(answers){
    if(busy || !evaluation)return;
    function run(){
      busy=true;SafeT.loading(true);
      SafeT.api.post('/evals/'+evalNo+'/risk-answers',{revision:evaluation.revision,answers:answers})
        .done(function(doc){SafeT.catalogAI.clear();applyDocument(doc);dirty=false;SafeT.go('v-list');SafeT.toast('답변을 반영했습니다. 현재 조치 목록을 다시 확인해 주세요.');})
        .fail(apiError).always(function(){busy=false;SafeT.loading(false);});
    }
    if(dirty)saveDraft('v-list').done(run);else run();
  }
  function payload() {
    return {revision:evaluation.revision,items:items.map(function(it){
      function action(a){return {id:typeof a.id==='number'?a.id:null,text:a.text,checked:a.checked};}
      return {id:it.id,curr:it.curr.map(action),plans:it.plans.map(action),none:it.none,controls_reviewed:!!it.controls_reviewed,keep:it.keep,owner:it.owner,due:it.due?it.due.replace(/\./g,'-'):null};
    })};
  }
  function itQuestions(){return items.some(function(it){return it.catalog && it.catalog.ai_analysis && it.catalog.ai_analysis.questions.length;});}
  function apiError(e) {
    SafeT.toast(e.message);
    if(e.errors && e.errors.length) openDetail(e.errors[0].index,'all',e.errors[0].field);
  }

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
    if ((!it.none && !checkedCount(it.curr)) || (it.catalog && !it.controls_reviewed)) m.push('current');
    if (it.signal === 'N') m.push('signal');
    if (it.signal === 'G' && !it.keep) m.push('plan');
    if (needsPlan(it) && !checkedCount(it.plans)) m.push('plan');
    if (needsPlan(it) && checkedCount(it.plans) && (!it.owner || !it.due)) m.push('owner');
    return m;
  }
  function has(arr, v) { return $.inArray(v, arr) > -1; }
  function needA(it) { var m = missing(it); return has(m, 'current') || has(m, 'signal') || has(m, 'plan'); }
  function needB(it) { return has(missing(it), 'owner'); }
  /** 후속업무: 빨강·노랑 + 대책을 추가한 초록 (판단 필요 제외) */
  function isFollow(it) { return it.signal !== 'N' && needsPlan(it); }
  /** 담당자미지정: 담당자·예정일이 필요한데 하나라도 비어 있음 */
  function ownerMissing(it) { return isFollow(it) && (!it.owner || !it.due); }

  function no(i) { return (i < 9 ? '0' : '') + (i + 1); }

  function signalEl(sig) {
    return $('<span class="signal" role="img"><i></i><i></i><i></i></span>')
      .attr('data-signal', sig).attr('aria-label', '위험 신호 ' + SIGNAL_TEXT[sig]);
  }

  var dirty = false;
  function markDirty() { dirty = true; }

  // 로그아웃 확인에서 사용 (api.js)
  SafeT.hasUnsaved = function () { return dirty || (SafeT.catalogAI && SafeT.catalogAI.hasDraft()); };

  /* ---------- S05 리스트 ---------- */
  var filter = 'all';

  function stateText(it) {
    var parts = [];
    var nc = checkedCount(it.curr);
    var np = checkedCount(it.plans);
    if (it.signal === 'N') parts.push('판단 필요');
    parts.push(it.none ? '현재 조치 없음' : (nc ? '현재 조치 ' + nc + '개' : '현재 조치 확인 필요'));
    if (it.signal === 'G' && !it.keep) {
      parts.push('유지 또는 대책 추가 선택 필요');
    } else if (it.signal === 'G' && it.keep === 'Y') {
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
    var first = null;   // 화면에 보이는 입력 필요 항목 중 첫 번째 → 눌러서 시작하도록 강조
    $.each(items, function (i, it) {
      if (filter === 'input' && !needA(it)) return;
      if ((filter === 'owner' || filter === 'follow') && !ownerMissing(it)) return;   // follow: 예전 저장 상태
      var need = missing(it).length > 0;
      var $a = $('<a class="card risk-card" href="#v-risk">').attr('data-index', i).toggleClass('card--need', need);
      if (need && first === null) {
        first = i;
        $a.addClass('card--start').attr('aria-label', no(i) + ' ' + it.job + ' · 여기부터 입력해 주세요');
        $('<span class="card__start">여기부터 입력 →</span>').appendTo($a);
      }
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
      $('<li class="empty">').text(filter === 'input' ? '입력이 필요한 항목이 없어요.' : '담당자를 지정하지 않은 항목이 없어요.').appendTo($ol);
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
    var ownerDone = $.grep(items, function (it) { return isFollow(it) && !ownerMissing(it); }).length;
    $('#count-input-done').text(items.length - a);
    $('#v-list .draft__progress .js-total').text(items.length);
    $('#count-owner-done').text(ownerDone);
    $('#count-owner-total').text(f);
    $('#need-row-a').prop('hidden', !a);
    $('#btn-input').prop('hidden', !a).text(touched ? '이어서 입력' : '입력 시작');
    $('#need-row-b').prop('hidden', !b);
    // 일괄 지정 링크는 대책·조치 입력 여부와 관계없이 항상 보임
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
          .text(a.ai ? (evaluation && evaluation.generation_source==='demo' ? '시험 후보' : '추천 후보') : '직접 추가'));
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
      if(it.catalog){
        var review=$('<label class="check">').appendTo($list);
        $('<input type="checkbox" data-kind="reviewed">').prop('checked',!!it.controls_reviewed).appendTo(review);
        $('<span>').text('이 작업에 해당하며 현재 조치 목록 전체를 확인했습니다. 선택한 조치는 실제 적용·작동 중이고 미선택 조치는 실시하지 않습니다.').appendTo(review);
      }
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
      // 전체 보기 마지막: 담당자·예정일 지정할 항목이 있으면 '다음' → 일괄 지정, 없으면 비활성
      next: state.index < items.length - 1 ? state.index + 1 : (ownerPending() ? 'end' : null)
    };
  }
  /** 담당자·예정일을 아직 지정하지 않은 후속업무 항목이 있는지 */
  function ownerPending() { return items.some(function (it) { return needB(it); }); }

  function renderDetail() {
    var it = cur();
    if (!it) { SafeT.go('v-list'); return; }
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
    if(it.catalog)$('#d-judge-box p').text('실시 중인 조치 또는 조치 없음을 선택하고, 목록 전체 확인 후 저장해 주세요.');

    if(SafeT.catalogAI)SafeT.catalogAI.detail(it);
    renderChecks($('#d-curr-list'), it.curr, 'curr', it);

    $('#d-green-switch').prop('hidden', !isG);
    if (isG) { $('#d-green-switch input').prop('checked',false); if(it.keep) $('#d-green-switch input[value="'+it.keep+'"]').prop('checked',true); }
    var showPlan = !isN && (!isG || it.keep === 'N');
    $('#d-keep-note').prop('hidden', !(isG && it.keep === 'Y'));
    $('#d-plan-wait').prop('hidden', !isN);
    $('#d-plan-body').prop('hidden', !showPlan);
    $('#d-plan-req').prop('hidden', !showPlan && !isG);   // 초록은 '유지/대책 추가' 선택 자체가 필수
    var greenNeed = isG && !it.keep;
    $('#d-green-need').prop('hidden', !greenNeed);
    $('#d-green-switch').toggleClass('segmented--need', greenNeed);
    if (showPlan) {
      renderChecks($('#d-plan-list'), it.plans, 'plan', it);
      renderOwner(it);
    }

    if(!$('#d-projection').length)$('<p id="d-projection" class="hint" aria-live="polite">').insertAfter('#d-plan-body');
    $('#d-projection').text(it.catalog ? (it.judged ? '개선대책 이행 시 예상 위험도: '+({R:'상',Y:'중',G:'하',N:'확인 필요'}[it.after])+' · 계획 이행과 효과를 가정한 값입니다.' : '예상 위험도: 저장 후 계산 · 실제 개선 결과와 구분합니다.') : '');
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
    signal: '현재 조치 목록 전체를 확인하고 저장해 주세요.',
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
      if(cur().signal==='G' && !cur().keep){
        // 이미 보이는 노란 안내(#d-green-need)를 그대로 사용해 같은 문구를 두 번 띄우지 않음
        $msg=$('#d-green-need');$focus=$('#d-green-switch input').first();
      }else{ $('#d-plan-list').before($msg);$focus=$('#d-plan-list input').first(); }
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
    if (kind === 'curr') {it.none = false;it.controls_reviewed=false;}
    if(it.catalog){it.judged=false;$('#d-projection').text('변경됨 · 저장 후 위험도를 다시 계산합니다.');}
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

  /** quiet=true: 저장 알림을 띄우지 않음 (부른 쪽이 완료 창 등 따로 안내할 때) */
  function saveDraft(back, confirm, quiet) {
    if(busy || !evaluation) return $.Deferred().reject().promise();
    busy=true; SafeT.loading(true);
    var request=confirm ? SafeT.api.post('/evals/'+evalNo+'/confirm',payload()) : SafeT.api.put('/evals/'+evalNo,payload());
    request.done(function(doc){
      applyDocument(doc);dirty=false;
      if(confirm){
        try {sessionStorage.setItem('safet.home',JSON.stringify({tab:'C',from:doc.eval_dt.slice(0,10).replace(/-/g,'.'),to:doc.eval_dt.slice(0,10).replace(/-/g,'.'),work:String(doc.work_no),page:1,scroll:0}));}catch(e){}
        // SH v3 25~27쪽: 확정 직후에는 이 문서의 읽기 전용 화면으로 이동.
        if(SafeT.current)SafeT.current.setEval(doc.eval_no);
        window.location.href=SafeT.current?'result.html':'result.html?eval='+doc.eval_no;
      } else {SafeT.go(back || 'v-list');if(back==='v-risk')renderDetail();if(!quiet)SafeT.toast('평가표를 저장했어요');}
    }).fail(apiError).always(function(){busy=false;SafeT.loading(false);$('#btn-confirm-ok').prop('disabled',false);});
    return request;
  }

  /* ---------- 로그인 만료 시 편집 내용 보관 · 다시 로그인하면 복구 (설계서 07쪽) ---------- */
  if (SafeT.auth) {
    SafeT.auth.onExpire(function () {
      if (!SafeT.hasUnsaved()) return null;
      return { page: 'draft', data: { email:(SafeT.auth.user() || {}).email, evalNo:evalNo, revision:evaluation && evaluation.revision, items: items, state: state, filter: filter, aiAnswers:SafeT.catalogAI && SafeT.catalogAI.snapshot() } };
    });
  }

  function restoreAfterLogin() {
    var r = SafeT.auth && SafeT.auth.takeRestore('draft');
    if (!r || r.email!==(SafeT.auth.user() || {}).email || r.evalNo!==evalNo || r.revision!==evaluation.revision || !$.isArray(r.items)) return false;
    items = $.map(r.items, function (it) { return makeItem(it); });
    state = $.extend({ index: 0, mode: 'all', needList: [] }, r.state);
    filter = r.filter || 'all';
    if(SafeT.catalogAI){SafeT.catalogAI.restore(r.aiAnswers);SafeT.catalogAI.summary(evaluation,submitAnswers);}
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
    // C02 삭제: 확인 창(#delete) → DELETE /evals/{번호} → 휴지통(30일 보관). 작성 중 평가표만 (서버도 확인)
    // 삭제 후에는 내 평가표로 이동해 알림만 띄움 (휴지통 화면으로 가지 않음 · 2026-11-17 결정)
    $('.draft__delete').on('click',function(e){ if(!evaluation || busy){e.preventDefault();} });
    $('#delete .btn--danger').attr('href','#v-list').on('click',function(e){
      e.preventDefault();
      if(busy || !evaluation) return;
      SafeT.closeModal(true);
      busy=true; SafeT.loading(true);
      SafeT.api.del('/evals/'+evalNo).done(function(){
        dirty=false; SafeT.hasUnsaved=function(){return false;};   // 삭제한 평가표는 '저장 안 함' 경고를 띄우지 않음
        if(SafeT.current) SafeT.current.setEval(null);
        window.location.href='home.html?deleted=1';
      }).fail(apiError).always(function(){busy=false;SafeT.loading(false);});
    });
    $('#risk-list').empty();
    $('#btn-save,#btn-confirm,#btn-input,#btn-bulk').attr('aria-disabled','true');
    if(!evalNo){SafeT.toast('내 평가표에서 평가표를 선택해 주세요.');return;}
    SafeT.loading(true);
    SafeT.api.get('/evals/'+evalNo).done(function(doc){
      if(doc.eval_status!=='W'){location.replace(SafeT.current?'result.html':'result.html?eval='+evalNo);return;}
      applyDocument(doc);
      if(restoreAfterLogin()){renderList();SafeT.toast('저장 전 편집 내용을 복구했어요.');}
      $('#btn-save,#btn-confirm,#btn-input,#btn-bulk').removeAttr('aria-disabled');
      SafeT.go('v-list');
    }).fail(apiError).always(function(){SafeT.loading(false);});
    window.addEventListener('beforeunload',function(e){if(SafeT.hasUnsaved()){e.preventDefault();e.returnValue='';}});

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

    $('#btn-bulk').on('click', function (e) {
      e.preventDefault();
      if ($(this).attr('aria-disabled') === 'true') return;
      SafeT.go('v-bulk', { only: null, back: 'v-list' });
    });

    // 목록의 '평가표 저장': 화면이 그대로라 저장 여부를 놓치기 쉬움 → 완료 창으로 결과와 나가는 길을 함께 보여 줌
    // (나가기 확인·추가 질문 답변 전 저장 등 다른 곳의 saveDraft 는 완료 창 없이 기존대로)
    $('#btn-save').on('click', function (e) {
      e.preventDefault();
      saveDraft('v-list', false, true).done(function () { SafeT.openModal('saved'); });
    });

    // 내 평가표로 나갈 때: '작성 중' 탭·사업장 -전체-·평가일이 들어간 기간으로 열어 이 평가표가 바로 보이게
    function homeShowsThis() {
      try {
        var s = JSON.parse(sessionStorage.getItem('safet.home') || '{}');
        var today = SafeT.today();
        var d = evaluation && evaluation.eval_dt ? String(evaluation.eval_dt).slice(0, 10).replace(/-/g, '.') : '';
        s.tab = 'W'; s.page = 1; s.scroll = 0; s.work = '';
        if (!s.from) s.from = SafeT.formatDate(new Date(today.getFullYear(), today.getMonth(), 1));
        if (!s.to) s.to = SafeT.formatDate(today);
        if (d) { if (s.from > d) s.from = d; if (s.to < d) s.to = d; }
        sessionStorage.setItem('safet.home', JSON.stringify(s));
      } catch (err) { /* 저장 불가 환경 */ }
    }
    // 위쪽 '← 내 평가표'는 저장 안 한 변경이 있으면 아래 '나가기 확인'이 먼저 물어봄
    $('.draft__back').on('click', homeShowsThis);
    // 저장 완료 창의 '내 평가표로': 방금 저장했으니 바로 이동
    $('#saved-home').on('click', function (e) {
      e.preventDefault();
      homeShowsThis();
      SafeT.closeModal(true);
      window.location.href = 'home.html';
    });

    $('#btn-confirm').on('click', function (e) {
      e.preventDefault();
      if(!evaluation || !items.length || busy)return;
      SafeT.openModal('confirm');
    });

    // 확인 창이 열릴 때 필수값 검사 (주소로 열어도 동일). 빠진 값이 있으면 창 대신 해당 필드로
    $('#confirm').on('safet:open', function () {
      if(!evaluation || !items.length || busy){SafeT.closeModal(true);return;}
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
      SafeT.closeModal(true);
      saveDraft('v-list',true);
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
      if (n === 'end') {
        // 마지막 항목 다음: 담당자·예정일 지정할 항목이 있으면 일괄 지정으로 바로, 없으면 리스트로
        if (ownerPending()) {
          SafeT.go('v-bulk', { only: null, back: 'v-list' });
          SafeT.toast('마지막 항목이에요. 담당자·예정일을 지정해 주세요.');
        } else {
          SafeT.go('v-list');
        }
        return;
      }
      if (n === null) return;
      state.index = n;
      renderDetail();
      window.scrollTo(0, 0);
    });

    $('#d-save').on('click', function () {
      if (busy || !evaluation) return;
      SafeT.confirm({title:'평가표 저장',message:'이 항목만이 아니라 평가표 전체를 저장해요. 저장할까요?',ok:'저장',cancel:'취소'})
        .then(function (yes) { if (yes) saveDraft('v-risk'); });
    });

    $('#d-rejudge').on('click',function(){if(evaluation.generation_source==='catalog_ai_v1' && itQuestions()){SafeT.go('v-list');$('#ai-question-panel textarea').first().trigger('focus');return;}if(['catalog_v1','catalog_ai_v1'].indexOf(evaluation.generation_source)!==-1){saveDraft('v-risk');return;}SafeT.toast('실제 위험 판단 모델 연결 후 다시 판단할 수 있어요. 현재 입력은 저장할 수 있습니다.');});

    // 체크 변경 (현재 조치 · 현재 조치 없음 · 개선대책)
    $('#risk-form').on('change', 'input[data-kind]', function () {
      var it = cur();
      var kind = $(this).data('kind');
      var on = this.checked;
      if(kind === 'reviewed'){it.controls_reviewed=on;}
      else if (kind === 'none') {
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
      if(it.catalog){
        if(kind==='curr' || kind==='none'){it.controls_reviewed=false;$('#d-curr-list input[data-kind=reviewed]').prop('checked',false);}
        it.judged=false;$('#d-projection').text('변경됨 · 저장 후 위험도를 다시 계산합니다.');
        if(kind!=='plan')$('#d-reason').text('현재 조치 변경 · 저장 후 재계산 필요');
      }
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
      if (kind === 'curr') {it.curr = $.grep(it.curr, function (a) { return a.id !== id; });it.controls_reviewed=false;it.judged=false;}
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

    // 키워드 후보 확인 후 추가. 서버 저장 전에 현재 편집을 먼저 보존.
    $('#add-form').on('safet:submit',function(e){
      e.preventDefault();var kw=normalize($('#keyword').val());
      $('#add-keyword').text(kw);
      $('#add-candidates').empty().append($('<label class="check">').append('<input type="checkbox" checked>').append($('<span class="check__text">').text(kw+' 관련 위험 항목 추가')));
      $('#add-empty').prop('hidden',true);SafeT.go('v-add-select');
    });
    $('#select-form').on('safet:submit',function(e){
      e.preventDefault();if(!$('#add-candidates input:checked').length){SafeT.toast('추가할 항목을 선택해 주세요.');return;}
      var kw=$('#add-keyword').text();
      saveDraft('v-add-select').done(function(){
        busy=true;SafeT.loading(true);
        SafeT.api.post('/evals/'+evalNo+'/items',{revision:evaluation.revision,keyword:kw}).done(function(doc){applyDocument(doc);dirty=false;$('#keyword').val('');SafeT.go('v-list');})
          .fail(apiError).always(function(){busy=false;SafeT.loading(false);});
      });
    });
    $('#v-saving').on('safet:show',function(){SafeT.go('v-list');});

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
          saveDraft('v-list').done(function () { window.location.href = href; });
        }
      });
    });
  });
})(jQuery, window.SafeT);
