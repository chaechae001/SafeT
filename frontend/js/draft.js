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
  var serverItems = [];        // 마지막 저장 기준 항목(깊은 복사). 항목만 저장할 때 다른 항목은 이 값으로 보냄
  var dirtySet = {};           // 저장하지 않은 입력이 있는 항목 위치
  var evalNo = Number(new URLSearchParams(location.search).get('eval')) || (SafeT.current && SafeT.current.evalNo());
  if(evalNo && SafeT.current)SafeT.current.setEval(evalNo);
  function applyDocument(doc) {
    evaluation = doc;
    serverItems = JSON.parse(JSON.stringify(doc.items));
    items = JSON.parse(JSON.stringify(doc.items)).map(makeItem);   // 서버 기준 사본과 객체를 나눔
    // 현재 조치를 이미 고른 항목은 '목록 확인'도 한 것으로(화면에서 긴 확인 체크를 뺐기 때문)
    items.forEach(function (it) { if (it.catalog && !it.controls_reviewed && (it.none || (it.curr || []).some(function (a) { return a.checked; }))) it.controls_reviewed = true; });
    // 작성자는 '평가담당자'로 맨 위에 표시(대책 담당자 기본값), 나머지는 참여자
    PEOPLE = [doc.eval_writer].concat(doc.members).filter(function(n,i,a){return n && a.indexOf(n)===i;}).map(function(n){return {name:n,role:n===doc.eval_writer?'평가담당자':'참여자'};});
    $('#v-list h1').first().text(doc.eval_nm);
    $('#d-reason-box .src').text(doc.generation_source==='demo'?'시험용 고정 신호':'판단 대기');
    $('.disclaimer').text(doc.generation_source==='demo' ? '개발 시험용 합성 평가표 · 실제 현장 판정에 사용하지 마세요.' : '실제 위험 판단 모델 미연결 · 판단 필요 항목은 확정할 수 없습니다.');
    if(['catalog_v1','catalog_ai_v1','catalog_rls_v1'].indexOf(doc.generation_source)!==-1){ $('.disclaimer').text('체크한 조치로 계산한 위험도예요. 최종 판단은 담당자가 해요.');$('#d-reason-box .src').text('DB 기준'); }
    if(doc.assessment_mode==='input_based'){
      $('.disclaimer').text('입력 기반 위험성평가표 · 미확인 조치는 실제 미실시와 구분하여 표시합니다.');
      $('#d-reason-box .src').text('입력·문헌 기준');
    }
    $('a[href="#v-add"]').prop('hidden',doc.assessment_mode==='input_based');
    if(SafeT.catalogAI)SafeT.catalogAI.summary(doc,submitAnswers);
    renderPending(doc);
    // 안내 패널은 스크롤 영역 맨 위로 (고정 영역을 늘리지 않음)
    $($('#ai-question-panel, #rag-status-panel, #rls-pending-panel').get().reverse()).each(function () { $(this).prependTo('#draft-scroll'); });
    $('.js-delete-count').text(doc.items.length);
    renderList();
  }
  /** 확인 대기: 기기에서만 나온 위험(catalog_rls_v1). 담당자가 실제 작업인지 확인해 추가해야 평가표 행이 된다.
      새 평가표에서는 사업장 등록 기기 위험이 처음부터 일반 행이고, 대기는 이번 평가에만 추가한 미등록 기기(사진 탐지·직접 추가)뿐.
      예전 평가표에 저장된 등록 기기 대기 항목은 machine_kind 가 'registered' 로 와서 지금처럼 '등록 기기'로 보인다.
      따로 모은 '확인 대기' 패널은 없애고, 목록 맨 뒤에 일반 카드와 같은 모양으로 그린다(renderList).
      카드를 누르는 순간(담당자 행동) 기존 add 호출로 행을 만들고, 휴지통·밀어서 삭제는 dismiss(제외). 자동 추가하지 않는다. */
  function pendingRows(){ return (evaluation && evaluation.pending_rows) || []; }
  function renderPending(){ $('#rls-pending-panel').remove(); }
  function fromMachine(it){ return !!(isRls(it) && it.catalog.risk_law.card && it.catalog.risk_law.card.from_machine); }
  function machineKind(it){ return (it && it.catalog && it.catalog.risk_law && it.catalog.risk_law.card && it.catalog.risk_law.card.machine_kind) || 'registered'; }
  function machineBadge(kind){ return $('<span class="machine-badge">').toggleClass('machine-badge--extra', kind === 'unregistered').text(kind === 'unregistered' ? '추가 기기' : '등록 기기'); }
  function machineWord(kind){ return kind === 'unregistered' ? '이번 평가에 추가한 기기' : '등록 기기'; }
  /** 대기 카드로 안내(확정 시도 때): 전체 보기로 바꾸고 첫 대기 카드를 가운데로 + 잠깐 강조 */
  function gotoPending(){
    if(filter!=='all'){filter='all';$('#v-list .tabs [data-filter]').removeAttr('aria-current').filter('[data-filter="all"]').attr('aria-current','page');}
    SafeT.go('v-list');renderList();
    var $card=$('#risk-list a[data-pending]').first();if(!$card.length)return;
    $card[0].scrollIntoView({block:'center',behavior:SafeT.reduceMotion?'auto':'smooth'});
    $card.addClass('is-returned');$card[0].focus({preventScroll:true});
    setTimeout(function(){$card.removeClass('is-returned');},1800);
  }
  function reviewPending(sid,decision){
    if(busy || !evaluation)return;
    function run(){
      busy=true;SafeT.loading(true);
      SafeT.api.post('/evals/'+evalNo+'/pending-rows',{revision:evaluation.revision,scenario_id:sid,decision:decision})
        .done(function(doc){applyDocument(doc);dirty=false;
          if(decision==='add'){
            // 추가된 행의 상세를 바로 연다
            var idx=-1;$.each(items,function(i,it){if(idx<0 && it.catalog && it.catalog.scenario && it.catalog.scenario.id===sid)idx=i;});
            // '평가표에 추가했어요' 알림은 빼고 상세만 연다(카드를 누른 것 자체가 추가 동작이라 알림이 오류처럼 보였음)
            if(idx>-1){openDetail(idx,'all');toTop();}
            else{SafeT.go('v-list');}
          } else {SafeT.go('v-list');SafeT.toast('평가표에서 제외했어요.');}})
        .fail(apiError).always(function(){busy=false;SafeT.loading(false);});
    }
    if(dirty)saveDraft('v-list').done(run);else run();
  }
  /** 대기 카드 휴지통·밀어서 삭제 = 제외(dismiss) */
  function dismissPending(sid){
    var c=null;$.each(pendingRows(),function(_,p){if(p.scenario_id===sid)c=p;});
    if(!c || busy || !evaluation)return;
    SafeT.confirm({
      title: c.job+' 항목을 평가표에서 제외할까요?',
      message: machineWord(c.machine_kind)+'('+(c.machine||'')+') 기준으로 찾은 위험이에요. 실제로 하지 않는 작업이면 제외해 주세요. 제외한 위험은 목록에 다시 나타나지 않아요.',
      ok: '평가표에서 제외', cancel: '취소', danger: true
    }).then(function(yes){ if(yes===true)reviewPending(sid,'dismiss'); });
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
  function payload(list) {
    return {revision:evaluation.revision,excluded_review_candidates:$('#rag-status-panel .candidate-exclusion:checked').map(function(){return this.value;}).get(),items:(list || items).map(function(it){
      function action(a){return {id:typeof a.id==='number'?a.id:null,text:a.text,checked:a.checked};}
      return {id:it.id,work_reviewed:!!it.work_reviewed,curr:it.curr.map(action),plans:it.plans.map(action),none:it.none,controls_reviewed:!!it.controls_reviewed,keep:it.keep,owner:it.owner,due:it.due?it.due.replace(/\./g,'-'):null};
    })};
  }
  function itQuestions(){return items.some(function(it){return it.catalog && it.catalog.ai_analysis && it.catalog.ai_analysis.questions.length;});}
  function apiError(e) {
    SafeT.toast(e.message);
    if(e.errors && e.errors.length) openDetail(e.errors[0].index,'all',e.errors[0].field);
  }

  /* ---------- 규칙 (건수 계산과 확정 검사는 같은 함수) ---------- */
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
    // 일반 평가표(catalog_rls_v1)는 현재 조치 선택 또는 '현재 조치 없음'만 확인한다. 다른 DB 기준 유형은 목록 전체 확인도 필요.
    if (it.assessment_mode!=='input_based' && ((!it.none && !checkedCount(it.curr)) || (it.catalog && !isRls(it) && !it.controls_reviewed))) m.push('current');
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

  function no(i) { return (i < 9 ? '0' : '') + (i + 1); }

  /** 위험도 표시 = 색 점 + 글자 칩 (상·중·하·판단 전). 색만으로 구분하지 않음 */
  var GRADE_TEXT = { R: '상', Y: '중', G: '하', N: '판단 전' };
  function signalEl(sig) {
    return $('<span class="risk-chip">').attr('data-signal', sig || 'N')
      .attr('aria-label', '현재 위험도 ' + GRADE_TEXT[sig || 'N'])
      .append($('<i aria-hidden="true">'), document.createTextNode(GRADE_TEXT[sig || 'N']));
  }

  /** 위험도 = 글자 없는 가로 3구 신호등(빨강·노랑·초록), 글자는 화면 읽기용 이름으로만 */
  var GRADE_NAME = { R: '상', Y: '중', G: '하', N: '판단 전' };
  function lightEl(sig) {
    sig = sig || 'N';
    return $('<span class="signal" role="img"><i></i><i></i><i></i></span>').attr({ 'data-signal': sig, 'aria-label': '위험도 ' + GRADE_NAME[sig], title: '위험도 ' + GRADE_NAME[sig] });
  }
  SafeT.lightEl = lightEl;
  /** 목록 카드 신호등. 계산된 등급이 있으면 그 색, 아직 판단 전(N)이고 현재 조치 입력이 필요하면 회색 신호등 옆에 '현재 조치 입력 전' */
  function signalWithNote(sig, needCurrent) {
    var $l = lightEl(sig);
    if ((sig || 'N') !== 'N' || !needCurrent) return $l;
    $l.attr({ 'aria-label': '위험도 판단 전 · 현재 조치 입력 전', title: '현재 조치 입력 전' });
    return $('<span class="signal-note">').append($l, $('<span class="signal-note__text" aria-hidden="true">현재 조치 입력 전</span>'));
  }

  var dirty = false;
  /** 변경 표시. idx 를 주면 그 항목, 위험 상세 화면이면 지금 항목 (항목별 저장) */
  function markDirty(idx) {
    dirty = true;
    var i = typeof idx === 'number' ? idx : ($('#v-risk').hasClass('is-active') ? state.index : null);
    if (i !== null) dirtySet[i] = true;
    if ($('#v-risk').hasClass('is-active')) updateFinish();
  }
  function clearDirty() { dirty = false; dirtySet = {}; }

  // 로그아웃 확인에서 사용 (api.js)
  SafeT.hasUnsaved = function () { return dirty || (SafeT.catalogAI && SafeT.catalogAI.hasDraft()); };

  /* ---------- S05 리스트 ---------- */
  var filter = 'all';

  function stateText(it) {
    var parts = [];
    var nc = checkedCount(it.curr);
    var np = checkedCount(it.plans);
    if (it.signal === 'N') parts.push('판단 필요');
    parts.push(it.none ? '현재 조치 없음' : (nc ? '현재 조치 ' + nc + '개' : it.assessment_mode==='input_based' ? '현재 조치 미확인' : '현재 조치 확인 필요'));
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
    $.each(items, function (i, it) {
      var need = missing(it).length > 0;
      if (filter === 'follow' && !isFollow(it)) return;
      if (filter === 'need' && !need) return;
      if (filter === 'owner' && !needB(it)) return;
      // 카드 상태 3가지 — 미작성(need) · 임시저장(temp: 입력했지만 아직 저장 안 함) · 작성 완료(done)
      var temp = !!dirtySet[i];
      var cstate = temp ? 'temp' : need ? 'need' : 'done';
      var $a = $('<a class="card risk-card" href="#v-risk">').attr('data-index', i).toggleClass('card--need', need);
      var $head = $('<span class="card__head">').appendTo($a);
      var $tt = $('<span class="card__title">').text(no(i) + ' ' + it.job).appendTo($head);
      if (fromMachine(it)) $tt.append(' ', machineBadge(machineKind(it)));      // 기기에서 온 항목(출처 표시)
      signalWithNote(it.signal, has(missing(it), 'current')).appendTo($head);
      $('<span class="card__meta">').text(it.factor + ' · ' + it.type).appendTo($a);
      var $st = $('<span class="risk-card__state">').appendTo($a);
      // 무엇이 남았는지 구체적으로 → 할 일은 아웃라인 버튼 모양, 완료·임시저장은 회색 배지
      var NEED = { current: '현재 조치 선택', signal: '저장해서 위험도 확인', plan: '개선대책 선택', owner: '담당자·예정일 지정' };
      if (cstate === 'temp') $('<span class="tag tag--temp">임시저장</span>').appendTo($st);
      else if (need) $('<span class="tag tag--todo">').text(NEED[missing(it)[0]] || '입력 필요').appendTo($st);
      else $('<span class="tag tag--done">✓ 작성 완료</span>').appendTo($st);
      $a.toggleClass('card--done', cstate === 'done').toggleClass('card--temp', cstate === 'temp').attr('data-state', cstate === 'temp' ? (need ? 'need' : 'done') : cstate).attr('data-card', cstate);
      $st.append($('<span class="risk-card__summary">').text(stateText(it)));
      var $li = $('<li class="risk-item">').append($a).appendTo($ol);
      // 항목별 삭제 (입력 기반 평가표는 분석 결과 유지라 숨김)
      // 편집 모드의 휴지통 버튼 + 왼쪽으로 밀면 드러나는 빨간 '삭제' 영역 (draft-edit.js)
      if (!evaluation || evaluation.assessment_mode !== 'input_based') {
        $li.addClass('is-deletable');
        $('<button class="risk-item__swipe-del" type="button" tabindex="-1">').html(SafeT.icon('trash') + '<span>삭제</span>')
          .attr({ 'data-delete-item': i, 'aria-label': no(i) + ' ' + it.job + ' 항목 삭제' }).prependTo($li);
        $('<button class="risk-item__delete" type="button">').html(SafeT.icon('trash'))
          .attr({ 'data-delete-item': i, 'aria-label': no(i) + ' ' + it.job + ' 항목 삭제' }).appendTo($li);
      }
    });
    // 확인 대기(기기 기준) 후보 = 목록 맨 뒤의 일반 카드(번호 이어서, 신호등 N, 할 일 '현재 조치 선택')
    // 누르면 add → 행이 되고 상세가 열림. 아직 행이 아니므로 '입력 필요'에 포함하고 담당자·후속업무 필터에는 넣지 않는다.
    if (filter === 'all' || filter === 'need') $.each(pendingRows(), function (k, c) {
      var n = items.length + k, label = no(n) + ' ' + c.job;
      var $a = $('<a class="card risk-card card--need card--pending" href="#v-risk" data-card="need" data-state="need">')
        .attr({ 'data-pending': c.scenario_id, 'aria-label': label + ' · ' + machineWord(c.machine_kind) + ' ' + (c.machine || '') + ' 기준 · 눌러서 평가표에 추가하고 현재 조치 선택' });
      var $head = $('<span class="card__head">').appendTo($a);
      $('<span class="card__title">').text(label).append(' ', machineBadge(c.machine_kind)).appendTo($head);
      signalWithNote('N', true).appendTo($head);
      $('<span class="card__meta">').text(c.title + ' · ' + c.type).appendTo($a);
      $('<span class="risk-card__state">').append($('<span class="tag tag--todo">').text('현재 조치 선택'),
        $('<span class="risk-card__summary">').text(machineWord(c.machine_kind) + ' ' + (c.machine || '') + ' 기준 · 실제 작업이면 선택')).appendTo($a);
      var $li = $('<li class="risk-item is-deletable is-pending">').append($a).appendTo($ol);
      // draft-edit.js 는 [data-delete-item] 이 붙은 버튼 누름을 막지 않으므로 같은 속성을 쓰고, 처리기는 data-dismiss-pending 을 먼저 본다
      $('<button class="risk-item__swipe-del" type="button" tabindex="-1">').html(SafeT.icon('trash') + '<span>제외</span>')
        .attr({ 'data-delete-item': 'pending', 'data-dismiss-pending': c.scenario_id, 'aria-label': label + ' 평가표에서 제외' }).prependTo($li);
      $('<button class="risk-item__delete" type="button">').html(SafeT.icon('trash'))
        .attr({ 'data-delete-item': 'pending', 'data-dismiss-pending': c.scenario_id, 'aria-label': label + ' 평가표에서 제외' }).appendTo($li);
    });
    $ol.find('.risk-card.card--need').first().addClass('is-next');      // 다음에 할 카드 하나만 떠 있음
    if ((items.length || pendingRows().length) && !$ol.children().length) {
      var EMPTY = { follow: '후속업무 항목이 없어요.', need: '입력이 필요한 항목이 없어요.', owner: '담당자가 비어 있는 항목이 없어요.' };
      $('<li class="empty">').text(EMPTY[filter] || '항목이 없어요.').appendTo($ol);
    }
    renderCounts();
  }

  /** 건수 요약(전체 / 입력 필요 / 담당자 미지정). 입력 필요 = 카드의 '입력 필요'와 같은 기준(missing) */
  function renderCounts() {
    var a = 0, b = 0, f = 0;
    $.each(items, function (_, it) {
      if (missing(it).length) a += 1;
      if (needB(it)) b += 1;
      if (isFollow(it)) f += 1;
    });
    var p = pendingRows().length, total = items.length + p;   // 확인 대기 후보도 건수에 포함(입력 필요)
    a += p;
    $('#need-a').text(a);
    $('#need-b').text(b);
    $('#need-total, #count-all, .js-total').text(total);
    $('#count-follow').text(f);
    $('#need-row-a').toggleClass('is-alert', a > 0);
    $('#need-row-b').toggleClass('is-alert', b > 0);
    $('#btn-input').prop('hidden', true);                     // 14: 입력 시작/이어서 입력 제거
    $('#done-box').prop('hidden', !total || !!a);
    $('#btn-confirm').prop('hidden', !total);
    $('#btn-confirm').toggleClass('btn--emphasis', !!total && !a);
    // 입력 필요가 남으면 연회색 비활성 모양(aria-disabled). common.css 의 pointer-events:none 은 draft.css 에서
    // 이 버튼만 되돌려(is-locked), 눌렀을 때 빠진 항목·대기 카드로 안내하는 기존 동작을 유지한다.
    $('#btn-confirm').toggleClass('is-locked', !!a).attr('aria-disabled', a ? 'true' : null)
      .attr('aria-label', a ? '평가표 확정 · 입력 필요 ' + a + '건 남음 · 누르면 입력할 항목으로 이동' : null);
    $('.js-delete-count').text(items.length);
  }

  var lastViewed = null;     // 목록으로 돌아올 때 강조할 항목

  /* ---------- S06 위험 상세 / S05-B 입력 필요 모드 ---------- */
  var state = { index: 0, mode: 'all', needList: [] };

  function cur() { return items[state.index]; }

  function openDetail(index, mode, focus) {
    state.index = index;
    state.mode = mode || 'all';
    SafeT.go('v-risk', { focus: focus || null });
  }

  /** 위험요인·법령 검색 모듈 연결 행(catalog_rls_v1). 생성 시(체크 0개)와 저장할 때마다 서버가 FOOD-3LEVEL-1.2로 계산한다. */
  function isRls(it) { return !!(it.catalog && it.catalog.risk_law); }
  function renderRls(it) {
    var $box = $('#d-rls').empty();
    $('#d-rls-box').prop('hidden', !isRls(it));
    if (!isRls(it)) return;
    var ref = it.catalog.risk_law, card = ref.card || {}, law = ref.law || {};
    $('<p>').text(ref.notice || 'AI 검색 결과 · 작성자 확인 후 사용').appendTo($box);
    $.each(ref.warnings || [], function (_, w) { $('<p class="hint">').text('주의: ' + w).appendTo($box); });
    // 등록 기기는 사업장 정기 작업의 기기라 '실제 작업 확인 필요' 문구를 뺌(출처만 표시)
    var unreg = card.machine_kind === 'unregistered';
    $('<p>').append($('<b>').text(card.from_machine ? (unreg ? '추가 기기 ' : '등록 기기 ') : '입력 문장 '),
      document.createTextNode(card.from_machine ? (card.input_text || '') + (unreg ? ' (이번 평가에 추가한 기기 · 담당자가 실제 작업으로 확인해 추가)' : ' (사업장 등록 기기)') : '“' + (card.input_text || '') + '”')).appendTo($box);
    $('<p>').append($('<b>').text('찾은 위험 카드 '), document.createTextNode((card.title || '') + ' (' + (card.card_id || '') + ')')).appendTo($box);
    $('<p>').append($('<b>').text('위험도 기준 '), document.createTextNode(it.catalog.scenario.title + ' · ' + ((ref.scenario_link || {}).message || ''))).appendTo($box);
    var $law = $('<p>').append($('<b>').text('관련 법령 후보 ')).appendTo($box);
    if (law.candidate) {
      $law.append(document.createTextNode(law.candidate.law_name + ' ' + (law.candidate.locator || '') + ' ' + (law.candidate.article_title || '')));
      $('<br>').appendTo($law);
    }
    $('<span class="muted">').text((law.candidate ? '' : (law.basis || '후보 없음') + ' · ') + (law.status || '')).appendTo($law);
    if ((ref.other_cards || []).length)
      $('<p>').append($('<b>').text('같은 기준으로 합친 카드 '), document.createTextNode($.map(ref.other_cards, function (c) { return c.title; }).join(', '))).appendTo($box);
    if ((ref.unmatched || []).length)
      $('<p class="muted">').text('평가표 행으로 만들지 못한 후보 ' + ref.unmatched.length + '개: ' + $.map(ref.unmatched, function (c) { return c.title + '(' + c.reason + ')'; }).join(', ')).appendTo($box);
  }

  /** 관련 근거(법적 기준). 위험요인·법령 검색 후보(risk_law.law.candidate) 또는 저장된 법령(it.law) */
  function lawOf(it) {
    var c = it.law_reference || (it.catalog && it.catalog.risk_law && it.catalog.risk_law.law);
    if (c && c.candidate) return { name: c.candidate.law_name, locator: c.candidate.locator, title: c.candidate.article_title,
      quote: c.candidate.quote, from: c.candidate.effective_from, status: c.status || '자동 검색 후보 · 적용 여부는 작성자가 확인' };
    if (it.law && it.law.name) return { name: it.law.name, locator: '', title: '', quote: it.law.summary || '', status: '' };
    return null;
  }
  function lawUrl(l) {
    var art = (l.locator || '').match(/^제\d+조(의\d+)?/);
    return 'https://www.law.go.kr/법령/' + encodeURIComponent((l.name || '').replace(/\s+/g, '')) + (art ? '/' + encodeURIComponent(art[0]) : '');
  }
  function renderLaw(it) {
    var l = lawOf(it);
    // 버튼에는 조문·제목(짧게 알아보기 쉬운 정보), 법령 이름은 창에서
    $('#d-law-open-name').text(l ? ([l.locator, l.title].filter(Boolean).join(' ') || l.name) : '찾지 못함');
    $('#d-law-open').attr('aria-label', l ? '관련 근거: ' + l.name + ' ' + (l.locator || '') + ' 보기' : '관련 근거 없음');
    $('#d-law-open').toggleClass('is-empty', !l);
  }
  function openLaw() {
    var it = cur(); if (!it) return;
    var l = lawOf(it), $b = $('#law-modal-body').empty();
    if (!l) {
      $('<p>').text('이 위험에 맞는 법적 기준을 찾지 못했어요. 담당자가 확인해 주세요.').appendTo($b);
    } else {
      $('<p class="law-modal__name">').text(l.name).appendTo($b);
      if (l.locator || l.title) $('<p class="law-modal__article">').text([l.locator, l.title].filter(Boolean).join(' · ')).appendTo($b);
      if (l.quote) $('<blockquote class="law-modal__quote">').text(l.quote).appendTo($b);
      if (l.status) $('<p class="hint">').text(l.status + (l.from ? ' · 시행 ' + l.from : '')).appendTo($b);
      $('<a class="btn btn--block" target="_blank" rel="noopener">').attr('href', lawUrl(l)).text('법령 원문 보기 (국가법령정보센터)').appendTo($b);
    }
    SafeT.openModal('law-modal');
  }

  function renderChecks($list, arr, kind, it) {
    $list.empty();
    if(kind==='curr' && it.assessment_mode==='input_based'){
      if(!arr.length)$('<p class="hint">').text('입력에서 실시가 확인된 안전조치가 없습니다. 조치가 없다고 판단한 것은 아닙니다.').appendTo($list);
      arr.forEach(function(a){$('<p>').text(a.text).appendTo($list);});
      return;
    }
    // 후보는 3개만 보임(체크한 후보·직접 추가는 항상 보임). 위험도 계산용 내부 문구(기준 조치 ID 등)는 화면에 표시하지 않음
    var shown = 0;
    // 개선대책 후보 중 이미 현재 안전조치로 고른 것('현재 조치 중')은 3개에 세지 않고, 그만큼 다음 후보를 더 보여 줌
    var inUse = {};
    if (kind === 'plan') $.each(it.curr || [], function (_, c) { if (c.checked) inUse[baseText(c.text)] = true; });
    $.each(arr, function (_, a) {
      var dup = kind === 'plan' && a.ai && !a.checked && inUse[baseText(a.text)];
      if (a.ai && !a.checked && !dup && shown >= 3) return;
      if (a.ai && !dup) shown += 1;
      var id = 'chk-' + a.id;
      var $row = a.ai ? $('<label class="check">') : $('<div class="check">');
      var $in = $('<input type="checkbox">').attr({ id: id, 'data-kind': kind, 'data-id': a.id }).prop('checked', a.checked);
      var $txt = a.ai ? $('<span class="check__text">') : $('<label class="check__text">').attr('for', id);
      $txt.text((a.ai ? a.text.replace(/\s*—\s*미실시·미흡 부분 개선$/, '') : a.text) + ' ');   // 반복 꼬리말은 화면에서만 숨김(저장 값은 그대로)
      if (!a.ai) $txt.append($('<span class="src src--manual">').text('직접 추가'));
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
      // '목록 전체 확인' 긴 체크는 화면에서 빼고, 현재 조치를 고르거나 '현재 조치 없음'을 체크하면 확인한 것으로 처리
      // (보이지 않는 후보는 '하지 않음'으로 계산되어 위험도가 낮아지지 않음)
    }
    if (kind === 'plan') markPlansInUse(it);
  }

  /** 현재 안전조치로 이미 고른 조치는 개선대책 목록에서 회색 비활성 + '현재 조치 중' 배지.
      (이미 대책으로 체크돼 있던 것은 체크를 풀 수 있게 누를 수 있는 상태로 두고 배지만 표시) */
  function baseText(t) { return String(t || '').replace(/\s*—\s*미실시·미흡 부분 개선$/, '').trim(); }
  function markPlansInUse(it) {
    var inUse = {};
    $.each(it.curr || [], function (_, a) { if (a.checked) inUse[baseText(a.text)] = true; });
    $('#d-plan-list input[data-kind="plan"]').each(function () {
      var id = $(this).data('id'), plan = null;
      $.each(it.plans || [], function (_, a) { if (a.id === id) plan = a; });
      var used = !!(plan && inUse[baseText(plan.text)]);
      var $row = $(this).closest('.check');
      $row.toggleClass('is-in-use', used).find('.in-use-badge').remove();
      // '현재 조치 중' 후보도 개선대책으로 고를 수 있게 둔다(저장 문구가 '… — 미실시·미흡 부분 개선'이라 개선대책이 맞고,
      // 고르면 '개선대책 1개 이상' 조건에 들어감). 회색은 고르기 전에만
      $(this).prop('disabled', false);
      if (used) $('<span class="in-use-badge">현재 조치 중</span>').appendTo($row);
    });
  }

  /** 예상 위험도 요약 카드 — 현재(신호등) → 개선 후 예상(신호등), 필수 추가 조치 강조, 안내 2줄 */
  var GRADE_SIG = { '상': 'R', '중': 'Y', '하': 'G' };
  function renderProjection(it) {
    if (!$('#d-projection').length) $('<section id="d-projection" class="proj-card" aria-live="polite">').insertAfter('#d-plan-body');
    var $p = $('#d-projection').empty().attr('class', 'proj-card');
    if (!it.catalog) { $p.prop('hidden', true); return; }
    $p.prop('hidden', false);
    var head = $('<div class="proj-card__head">').appendTo($p);
    $('<h3 class="proj-card__title">예상 위험도 분석</h3>').appendTo(head);
    if (it.assessment_mode === 'input_based') {
      $('<p class="proj-card__muted">').text('개선대책 선택은 계획으로 저장되며 입력 기반 현재 위험도를 변경하지 않습니다.').appendTo($p);
      return;
    }
    var pr = it.catalog.projected_result, controls = it.catalog.scenario && it.catalog.scenario.controls;
    var afterSig = it.after || (pr && GRADE_SIG[pr.grade]) || 'N';
    if (!it.judged || !(pr || (it.after && it.after !== 'N'))) {
      $p.addClass('is-pending');
      $('<p class="proj-card__muted">').text(it.judged ? '개선대책을 고르고 저장하면 예상 위험도를 계산해요.' : '바뀐 내용이 있어요. 저장하면 예상 위험도를 다시 계산해요.').appendTo($p);
      return;
    }
    var info = $('<button type="button" class="proj-card__info" aria-expanded="false" aria-label="계산 설명 보기">').html(SafeT.icon ? SafeT.icon('info') : 'i').appendTo(head);
    var row = $('<div class="proj-card__row">').appendTo($p);
    function side(label, sig) {
      return $('<span class="proj-card__side">').append($('<span class="proj-card__label">').text(label), lightEl(sig), $('<b class="proj-card__grade">').attr('data-signal', sig).text(GRADE_NAME[sig]));
    }
    row.append(side('현재', it.signal || 'N'), $('<span class="proj-card__arrow" aria-hidden="true">→</span>'), side('개선 후 예상', afterSig));
    var ps = pr && SafeT.riskText && SafeT.riskText.parse ? SafeT.riskText.parse(pr.reason, controls) : null;
    var tip = '';
    if (ps && ps.core.length && ps.next) tip = "'" + ps.core[0] + "'" + (ps.core.length > 1 ? ' 외 ' + (ps.core.length - 1) + '개' : '') + ' 추가 시 ' + SafeT.riskText.ro(ps.next) + ' 완화 가능';
    // '꼭 필요한 조치 ○○가 아직 남아 있어요' 코멘트는 숨김(화면 문구만 · 계산·critical 값은 그대로)
    else if (ps && ps.keep) tip = "남은 조치를 해도 위험의 크기 때문에 '" + ps.keep + "' 유지";
    if (tip) $('<p class="proj-card__tip">').html((SafeT.icon ? SafeT.icon('bulb') : '')).append($('<span>').text(tip)).appendTo($p);
    $('<ul class="proj-card__notes"><li>선택한 대책 모두 이행 시 예상되는 예측치입니다.</li><li>최종 안전 판단 및 관리는 담당자가 확인·수행합니다.</li></ul>').appendTo($p);
    if (pr && pr.reason) $('<p class="proj-card__detail">').text(pr && SafeT.riskText ? SafeT.riskText.friendly(pr.reason, controls) : '').appendTo($p);
    var full = $p.children(".proj-card__tip, .proj-card__notes, .proj-card__detail").prop("hidden", true);
    info.on('click', function () { var open = full.prop('hidden'); full.prop('hidden', !open); info.attr('aria-expanded', open ? 'true' : 'false'); });
  }

  function renderOwner(it) {
    var $v = $('#d-owner-value').empty();
    if (it.owner && it.due) {
      $('<span class="strong">').text(it.owner.name + ' · ' + it.due).appendTo($v);
      $('#d-owner-btn').text('담당자·예정일 변경');
    } else {
      $('<span class="strong muted">담당자·예정일 미지정</span>').appendTo($v);
      $('#d-owner-btn').text('담당자·예정일 지정');
    }
  }

  /** 현재 위치 뒤의 미완성 행, 확인 대기 카드 순서로 안내한다. 앞에서 건너뛴 항목은 종료 안내에서 다시 열 수 있다. */
  function nextOpen() {
    var after = $.grep(needIndexes(), function (i) { return i > state.index; });
    if (after.length) return after[0];
    return pendingRows().length ? 'pending' : null;
  }
  function navPos() {
    if (state.mode === 'need') {
      var k = $.inArray(state.index, state.needList), n = nextOpen();
      return {
        prev: k > 0 ? state.needList[k - 1] : null,
        next: n === null ? 'end' : n   // 남은 일이 없으면 리스트
      };
    }
    return {
      prev: state.index > 0 ? state.index - 1 : null,
      next: state.index < items.length - 1 ? state.index + 1 : nextOpen()
    };
  }

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
      $('#d-mode-link').html('<span aria-hidden="true">‹</span> 목록').attr('href', '#v-list');
    }

    $('#d-job').text(it.job);
    $('#d-signal, #d-signal-label').attr('data-signal', it.signal);
    $('#d-signal-text').text(SIGNAL_TEXT[it.signal]);
    $('#d-risk-chip').replaceWith(lightEl(it.signal).attr('id', 'd-risk-chip').addClass('signal--lg'));   // 글자 없는 신호등
    $('#d-type').text(it.type);
    $('#d-title').text(it.title);
    $('#d-desc').text(it.desc).prop('hidden', need || !it.desc);
    // 입력 필요 모드: 판단 이유·법령 대신 원인
    $('#d-cause').text(it.cause || '');
    $('#d-cause-box').prop('hidden', !need || !it.cause);
    $('#d-reason').text((SafeT.riskText ? SafeT.riskText.friendly(it.reason || '', it.catalog && it.catalog.scenario && it.catalog.scenario.controls) : (it.reason || '')));   // 쉬운 말로
    $('#d-reason-box').prop('hidden', !it.reason);   // 입력 필요 모드에서도 판단 이유는 펼치기로
    if (it.law) {
      $('#d-law-name').text(it.law.name);
      $('#d-law-summary').text(it.law.summary);
      $('#d-law-link').attr('href', it.law.url);
    }
    $('#d-law-box').prop('hidden', true);   // '관련 근거' 버튼·창으로 대체
    $('#d-judge-box').prop('hidden', !isN);
    if(it.catalog)$('#d-judge-box p').text('하고 있는 조치를 고르거나 ‘현재 조치 없음’을 체크한 뒤 저장해 주세요.');   // 짧게
    renderRls(it);
    renderLaw(it);

    if(SafeT.catalogAI)SafeT.catalogAI.detail(it);
    if(it.authoring){
      var reviewLabel=$('<label>').appendTo('#ai-evidence');
      $('<input type="checkbox" class="work-review">').prop('checked',!!it.work_reviewed).appendTo(reviewLabel)
        .on('change',function(){it.work_reviewed=this.checked;dirty=true;});
      reviewLabel.append(' 실제 작업과 입력 근거를 확인했습니다.');
    }
    renderChecks($('#d-curr-list'), it.curr, 'curr', it);
    $('[data-add="curr"]').prop('hidden',it.assessment_mode==='input_based');

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

    renderProjection(it);   // 긴 안내 문장 → 예상 위험도 요약 카드
    var pos = navPos();
    $('#d-prev').prop('disabled', pos.prev === null);
    updateFinish();   // '다음 항목' / '검토 마치기' 문구도 여기서(체크할 때마다 다시 계산)

    $('#risk-form .inline-add').remove();
    $('#risk-form .section').removeClass('is-invalid');
    SafeT.clearErrors($('#v-risk'));
    lastNext = null;
    updatePulse(false);
  }

  /** 지금 채울 블록 하나만 떠 있는 상태(.is-next). 반복 움직임 없음.
      사용자가 한 블록을 끝내면 다음 블록으로 옮기고 그 블록이 보이게 부드럽게 스크롤 */
  var lastNext = null;
  function nextTarget(it) {
    var m = missing(it);
    if (has(m, 'current')) return '#d-current';
    if (has(m, 'signal')) return dirty ? '#d-save' : '#d-current';        // 고른 뒤 저장해야 위험도가 나옴
    if (has(m, 'plan')) return '#d-plan';
    if (has(m, 'owner')) return '#d-plan .owner-box';
    if (dirtySet[state.index]) return '#d-save';                              // 다 채웠으면 저장
    return null;
  }
  function updatePulse(userAction) {
    var it = cur(); if (!it) return;
    var t = nextTarget(it);
    $('#v-risk .is-next').removeClass('is-next');
    $('#d-curr-list, #d-plan-list, #d-green-switch, #d-owner-btn').removeClass('ux-pulse');
    if (t) $(t).addClass('is-next');
    if (userAction && t && t !== lastNext && t !== '#d-save') {
      var el = $(t)[0];
      if (el) setTimeout(function () { el.scrollIntoView({ block: 'start', behavior: SafeT.reduceMotion ? 'auto' : 'smooth' }); }, 120);
    }
    lastNext = t;
  }


  /** 마지막 항목·모두 입력했을 때 안내 */
  function needIndexes() { var r = []; $.each(items, function (i, it) { if (missing(it).length) r.push(i); }); return r; }
  /** 확정 전에 남은 일 = 입력 필요 행 + 등록 기기 확인 대기 카드 + 확인하지 않은 검색 후보.
      예전에는 입력 필요 행만 세어, 대기 카드가 남아도 '모든 항목을 확인했어요'가 떴음 */
  function unchecked() { return $('#rag-status-panel .candidate-exclusion:not(:checked)').length; }
  function updateFinish() {
    if (!cur()) return;
    var pos = navPos();
    var last = pos.next === null || pos.next === 'end';
    $('#d-next').prop('disabled', false).text(last ? '검토 마치기' : '다음 항목').toggleClass('btn--finish', last)
      .attr('aria-label', pos.next === 'pending' ? '다음 항목: 기기 확인 대기' : null);
    var left = needIndexes(), others = $.grep(left, function (i) { return i !== state.index; });
    var pend = pendingRows().length, rag = unchecked();
    var allDone = items.length && !left.length && !pend && !rag;
    var atEnd = last;   // 다음에 열 카드(입력 필요 행·확인 대기 카드)가 있으면 안내 상자를 띄우지 않고 '다음 항목'으로
    var $f = $('#d-finish');
    var show = atEnd || allDone;
    $f.prop('hidden', !show).toggleClass('notice--done', !!(allDone && !dirty));
    if (!show) return;
    if (allDone && dirty) {
      $('#d-finish-title').text('모두 입력했어요');
      $('#d-finish-text').text('아직 저장하지 않은 입력이 있어요. 입력 내역을 저장한 뒤 목록에서 평가표를 확정해 주세요.');
    } else if (allDone) {
      $('#d-finish-title').text('모든 항목을 확인했어요');
      $('#d-finish-text').text("목록으로 돌아가 '평가표 확정'을 눌러 주세요.");
    } else {
      var parts = [];
      if (left.length) parts.push('입력이 필요한 항목 ' + left.length + '개');
      if (pend) parts.push('기기 기준 확인 대기 ' + pend + '개');
      if (rag) parts.push('확인하지 않은 후보 ' + rag + '개');
      $('#d-finish-title').text('아직 확인할 항목이 남았어요');
      $('#d-finish-text').text(parts.join(', ') + '가 남았어요.' + (dirty ? ' 저장하지 않은 입력도 있어요.' : ''));
    }
    $('#d-goto-need').prop('hidden', !others.length).text('남은 입력 필요 항목으로');
    $('#d-finish-save').prop('hidden', !dirty);
  }

  /** 목록으로 나갈 때 저장 안 된 입력이 있으면 묻기 (24) */
  function leaveToList(after) {
    if (!dirty) { SafeT.go('v-list'); if (after) after(); return; }
    SafeT.confirm({
      title: '저장하지 않은 입력이 있어요',
      message: '입력 내역을 저장하고 목록으로 갈까요? 저장하지 않아도 이 화면을 닫기 전까지 입력은 남아 있어요.',
      ok: '저장하고 목록으로', alt: '저장 없이 목록으로', cancel: '계속 입력'
    }).then(function (a) {
      if (a === true) { var d = saveDraft('v-list'); if (after && d && d.done) d.done(after); }
      else if (a === 'alt') { SafeT.go('v-list'); if (after) after(); }
    });
  }
  /** 다음·이전 항목·대기 카드를 열면 화면 맨 위(위험요인 제목)부터 보이게. 그리는 중 생기는 스크롤까지 한 번 더 */
  function toTop() {
    var go = function () { $('#risk-scroll').scrollTop(0); window.scrollTo(0, 0); };
    go(); requestAnimationFrame(go); setTimeout(go, 120);
  }
  /** 23: 지금 항목의 입력만 저장. 다른 항목은 마지막 저장값으로 보내고, 그 항목들의 저장 안 된 입력은 화면에 그대로 둠 */
  function saveCurrentItem() {
    if (busy || !evaluation) return;
    var idx = state.index;
    var local = items.slice();
    var send = $.map(serverItems, function (srv, i) { return i === idx ? items[i] : makeItem(JSON.parse(JSON.stringify(srv))); });
    busy = true; SafeT.loading(true);
    SafeT.api.put('/evals/' + evalNo, payload(send)).done(function (doc) {
      var keep = $.extend({}, dirtySet); delete keep[idx];
      applyDocument(doc);
      dirtySet = {};
      $.each(keep, function (i) { if (local[i] && items[i] && local[i].id === items[i].id) { items[i] = local[i]; dirtySet[i] = true; } });
      dirty = !$.isEmptyObject(dirtySet);
      renderList();
      SafeT.go('v-risk'); renderDetail();
      // 저장으로 위험도가 나오면 다음 칸(개선대책 등)으로 안내
      var $n = $('#v-risk .is-next').not('#d-save');
      if ($n.length) setTimeout(function () { $n[0].scrollIntoView({ block: 'start', behavior: SafeT.reduceMotion ? 'auto' : 'smooth' }); }, 150);
      SafeT.toast('저장했어요', 1300);   // 짧게(다음 작업을 가리지 않게)
    }).fail(apiError).always(function () { busy = false; SafeT.loading(false); });
  }

  /** 15: 항목 1개 삭제 → 바로 저장(서버). 저장 안 된 입력이 있으면 먼저 저장 */
  function deleteItem(i) {
    var it = items[i];
    if (!it || busy || !evaluation) return;
    SafeT.confirm({
      title: no(i) + ' ' + it.job + ' 항목을 삭제할까요?',
      message: '이 항목의 현재 조치·개선대책·담당자 입력도 함께 지워져요. 휴지통에 남지 않아 되돌릴 수 없어요.',
      ok: '항목 삭제', cancel: '취소', danger: true
    }).then(function (yes) {
      if (yes !== true) return;
      function run() {
        busy = true; SafeT.loading(true);
        SafeT.api.post('/evals/' + evalNo + '/items/' + items[i].id + '/delete', { revision: evaluation.revision })
          .done(function (doc) { applyDocument(doc); clearDirty(); SafeT.go('v-list'); SafeT.toast('항목을 삭제했어요.'); })
          .fail(apiError).always(function () { busy = false; SafeT.loading(false); });
      }
      if (dirty) saveDraft('v-list').done(run); else run();
    });
  }

  // 확정 시 빠진 값: 해당 필드로 이동해 그 자리에서 안내 (결정 13)
  var MISSING_MSG = {
    current: "현재 안전조치를 선택하거나 '현재 조치 없음'을 체크해 주세요.",
    signal: '현재 조치 목록 전체를 확인하고 저장해 주세요.',
    plan: '개선대책을 1개 이상 선택해 주세요.',
    owner: "'담당자·예정일 지정'을 눌러 담당자와 예정일을 넣어 주세요."
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
      $focus = $('#d-curr-list input').first();   // '다시 판단' 버튼 숨김 → 현재 조치로
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
    if (kind === 'curr') {it.none = false;it.controls_reviewed=true;}   // 직접 추가(체크됨) = 선택함
    if(it.catalog){it.judged=false;}
    if (kind === 'plan') { it.judged = false; applyDefaultOwner(it); }   // 담당자·예정일 기본값
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

  var assignSingle = false;      // 위험 상세에서 연 '이 항목만' 지정 창

  /** 21: 위험 상세에서 화면 전환 없이 이 항목의 담당자·예정일 지정 창 */
  function openAssignSingle() {
    assignSingle = true;
    fillAssign();
    var it = cur();
    if (it.owner) {
      $('#assign-form input[name="manager_type"][value="' + it.owner.type + '"]').prop('checked', true);
      if (it.owner.type === 'R') $('#assign-people input').filter(function () { return this.value === it.owner.name; }).prop('checked', true);
      else $('#manager_nm_manual').val(it.owner.name);
    }
    if (it.due) $('#due_dt').val(SafeT.formatDate(SafeT.parseDate(it.due)));
    $('#assign-title').text('담당자·예정일 지정');
    $('#assign .modal__body > .small.muted').first().text(no(state.index) + ' ' + it.job + ' 항목의 담당자와 예정일을 정해요.');
    $('#assign .modal__body > .notice').prop('hidden', true);
    $('#assign-form [type="submit"]').text('적용');
    $('#assign .modal__close').attr('href', '#v-risk');
    SafeT.openModal('assign');
  }

  function openAssign() {
    if (!$('#bulk-list input:checked').length) {
      SafeT.toast('지정할 항목을 선택해 주세요.');
      return;
    }
    assignSingle = false;
    fillAssign();
    $('#assign-title').text('담당자·예정일 일괄 지정');
    $('#assign .modal__body > .small.muted').first().html('선택한 <span class="js-bulk-count"></span>건에 같은 담당자와 예정일을 넣어요.');
    $('#assign .modal__body > .notice').prop('hidden', false);
    $('#assign-form [type="submit"]').html('<span class="js-bulk-count"></span>건에 적용');
    $('#assign .modal__close').attr('href', '#v-bulk');
    updateBulkCount();
    SafeT.openModal('assign');
  }

  /** 대책 담당자 기본값 = 평가담당자(작성자), 개선 예정일 기본값 = 작성일(평가일) */
  function defaultOwner() {
    if (!evaluation || !evaluation.eval_writer) return null;
    var d = SafeT.parseDate(String(evaluation.eval_dt || '').slice(0, 10));   // "2026-11-22T00:00:00" → 날짜만
    return { owner: { type: 'R', name: evaluation.eval_writer }, due: d ? SafeT.formatDate(d) : null };
  }
  function applyDefaultOwner(it) {
    var d = defaultOwner();
    if (!d || !it) return false;
    var changed = false;
    if (!it.owner) { it.owner = d.owner; changed = true; }
    if (!it.due && d.due) { it.due = d.due; changed = true; }
    return changed;
  }

  function fillAssign() {
    var $people = $('#assign-people').empty();
    $.each(PEOPLE, function (i, p) {
      var $l = $('<label class="check">');
      $('<input type="radio" name="manager_nm">').val(p.name).appendTo($l);
      $('<span class="check__text">').text(p.name + ' ').append($('<span class="muted">').text('· ' + p.role)).appendTo($l);
      $people.append($l);
    });
    $('#assign-form input[name="manager_type"][value="R"]').prop('checked', true);
    $('#manager_nm_manual, #due_dt').val('');
    var d = defaultOwner();   // 처음부터 평가담당자·작성일이 채워져 있음(바꿀 수 있음)
    if (d) {
      $('#assign-people input').filter(function () { return this.value === d.owner.name; }).prop('checked', true);
      if (d.due) $('#due_dt').val(d.due);
    }
    SafeT.clearErrors($('#assign-form'));
    $('#assign-people').removeClass('is-invalid');
  }

  function saveDraft(back, confirm) {
    if(busy || !evaluation) return $.Deferred().reject().promise();
    busy=true; SafeT.loading(true);
    var request=confirm ? SafeT.api.post('/evals/'+evalNo+'/confirm',payload()) : SafeT.api.put('/evals/'+evalNo,payload());
    request.done(function(doc){
      applyDocument(doc);clearDirty();
      if(confirm){
        try {sessionStorage.setItem('safet.home',JSON.stringify({tab:'C',from:doc.eval_dt.slice(0,10).replace(/-/g,'.'),to:doc.eval_dt.slice(0,10).replace(/-/g,'.'),work:String(doc.work_no),page:1,scroll:0,day:SafeT.formatDate(SafeT.today())}));}catch(e){}   // 같은 날 복원 규칙
        // 확정 직후에는 이 문서의 읽기 전용 화면으로 이동.
        if(SafeT.current)SafeT.current.setEval(doc.eval_no);
        window.location.href=SafeT.current?'result.html':'result.html?eval='+doc.eval_no;
      } else {SafeT.go(back || 'v-list');if(back==='v-risk')renderDetail();SafeT.toast('입력 내역을 저장했어요');}
    }).fail(apiError).always(function(){busy=false;SafeT.loading(false);$('#btn-confirm-ok').prop('disabled',false);});
    return request;
  }

  /* ---------- 로그인 만료 시 편집 내용 보관 · 다시 로그인하면 복구 ---------- */
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
    // 삭제 후에는 내 평가표로 이동해 알림만 띄움 (휴지통 화면으로 가지 않음)
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
      renderCounts();                                  // 확정 버튼 잠김 표시 다시 반영
      SafeT.go('v-list');
    }).fail(apiError).always(function(){SafeT.loading(false);});
    window.addEventListener('beforeunload',function(e){if(SafeT.hasUnsaved()){e.preventDefault();e.returnValue='';}});

    // 리스트
    $('#v-list').on('safet:show', renderList);
    // 상세에서 목록으로 오면 보던 항목 카드를 화면 가운데로 옮기고 잠깐 강조
    $('#v-risk').on('safet:hide', function () { lastViewed = state.index; });
    $('#v-list').on('safet:show', function () {
      if (lastViewed === null) return;
      var $card = $('#risk-list a[data-index="' + lastViewed + '"]');
      lastViewed = null;
      if (!$card.length) return;
      setTimeout(function () {
        $card[0].scrollIntoView({ block: 'center', behavior: SafeT.reduceMotion ? 'auto' : 'smooth' });
        $card.addClass('is-returned');
        setTimeout(function () { $card.removeClass('is-returned'); }, 1800);
      }, 50);
    });

    // 대기 카드를 누르는 순간 = 담당자가 실제 작업으로 확인 → add 후 그 항목 상세
    $('#risk-list').on('click', 'a[data-pending]', function (e) {
      e.preventDefault();
      reviewPending($(this).attr('data-pending'), 'add');
    });
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

    $('#v-list').on('change', '.candidate-exclusion', markDirty);

    $('#btn-confirm').on('click', function (e) {
      e.preventDefault();
      if(!evaluation || !(items.length || pendingRows().length) || busy)return;
      SafeT.openModal('confirm');
    });

    // 확인 창이 열릴 때 필수값 검사 (주소로 열어도 동일). 빠진 값이 있으면 창 대신 해당 필드로
    $('#confirm').on('safet:open', function () {
      if(!evaluation || !(items.length || pendingRows().length) || busy){SafeT.closeModal(true);return;}
      // 빠진 값이 있는 행 먼저(번호 순), 그다음 목록 맨 뒤의 대기 카드로 안내
      var firstMissing = -1;
      for (var k = 0; k < items.length; k += 1) { if (missing(items[k]).length) { firstMissing = k; break; } }
      if(firstMissing < 0 && pendingRows().length){
        SafeT.closeModal(true);
        gotoPending();   // 알림 없이 대기 카드로 이동·강조만
        return;
      }
      if($('#rag-status-panel .candidate-exclusion:not(:checked)').length){
        SafeT.closeModal(true);
        SafeT.toast('실제 작업이거나 아직 확인하지 않은 후보가 있어 확정을 보류합니다.');
        return;
      }
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
      // 머뭇거리면 Safe-T 캐릭터가 다음에 채울 칸을 가리킴(js/mascot.js)
      if (SafeT.mascot) SafeT.mascot.watch(function () {
        var it = cur(); if (!it || !$('#v-risk').hasClass('is-active')) return null;
        var t = nextTarget(it); if (!t) return null;
        var green = it.signal === 'G' && !it.keep;
        var text = { '#d-current': '지금 하고 있는 안전조치를 골라 주세요', '#d-plan': green ? '현재 상태 유지 또는 대책 추가를 골라 주세요' : '개선대책을 하나 이상 골라 주세요',
          '#d-plan .owner-box': '담당자와 예정일을 정해 주세요', '#d-save': '다 골랐으면 저장해 주세요' }[t] || '여기를 채워 주세요';
        var el = $(t)[0]; return el ? { el: el, text: text } : null;
      }, { idle: 8000 });
    });
    $('#v-risk').on('safet:hide', function () { if (SafeT.mascot) SafeT.mascot.stop(); });

    $('#d-mode-link').on('click', function (e) {
      e.preventDefault();
      if (state.mode === 'need') {               // 전체 보기: 원래처럼 전체 항목 이동
        state.mode = 'all';
        renderDetail();
        return;
      }
      leaveToList();                             // 저장 안 된 입력이 있으면 묻기
    });

    $('#d-prev').on('click', function () {
      var p = navPos().prev;
      if (p === null) return;
      state.index = p;
      renderDetail();
      toTop();
    });

    /* 빠진 필수 입력 안내는 '다음 항목'에서만, 한 번만.
       - '검토 마치기'(남은 일 없음)·확인 대기 카드로 가기는 막지 않음(목록에서 입력 필요 건수로 다시 안내)
       - 빠진 칸이 있으면 첫 누름에 그 칸을 알려 주고, 같은 항목에서 한 번 더 누르면 건너뜀
         (입력 필요 모드는 모든 항목이 미완성이라, 막으면 다음 항목으로 갈 수 없었음) */
    var skipWarned = null;
    $('#d-next').on('click', function () {
      var n = navPos().next;
      if (n === 'end' || n === null) { leaveToList(); return; }   // 마지막 항목 = 검토 마치기
      if (n === 'pending') { leaveToList(gotoPending); return; }                 // 남은 일이 확인 대기 카드뿐
      var m = missing(cur());
      if (m.length && skipWarned !== cur()) {
        skipWarned = cur();
        $('#v-risk .js-error').remove(); $('#risk-form .section').removeClass('is-invalid');
        focusMissing(m[0]);
        $('#v-risk .js-error').first().append(document.createTextNode(" 나중에 입력하려면 '다음 항목'을 한 번 더 눌러 주세요."));
        return;
      }
      skipWarned = null;
      if (state.mode === 'need' && $.inArray(n, state.needList) < 0) state.needList.push(n);   // 위치 표시(입력 필요 k / n) 유지
      state.index = n;
      renderDetail();
      toTop();
    });

    // '입력 내역 저장' = 지금 항목만 저장
    $('#d-save').on('click', saveCurrentItem);
    // 24: 모두 입력했을 때 안내의 저장 = 저장 안 된 입력 전부
    $('#d-finish-save').on('click', function () { if (!busy) saveDraft('v-risk'); });
    $('#d-goto-need').on('click', function () {
      var left = $.grep(needIndexes(), function (i) { return i !== state.index; });
      if (!left.length) return;
      state.needList = needIndexes();
      openDetail(left[0], 'need');
    });
    // 15: 항목별 삭제
    $('#risk-list').on('click', '[data-delete-item]', function (e) {
      e.preventDefault(); e.stopPropagation();
      if ($(this).is('[data-dismiss-pending]')) { dismissPending($(this).attr('data-dismiss-pending')); return; }
      deleteItem(+$(this).attr('data-delete-item'));
    });

    $('#d-rejudge').on('click',function(){if(evaluation.generation_source==='catalog_ai_v1' && itQuestions()){SafeT.go('v-list');$('#ai-question-panel textarea').first().trigger('focus');return;}if(['catalog_v1','catalog_ai_v1','catalog_rls_v1'].indexOf(evaluation.generation_source)!==-1){saveDraft('v-risk');return;}SafeT.toast('실제 위험 판단 모델 연결 후 다시 판단할 수 있어요. 현재 입력은 저장할 수 있습니다.');});

    // 체크 변경 (현재 조치 · 현재 조치 없음 · 개선대책)
    $('#risk-form').on('change', 'input[data-kind]', function () {
      // 체크하면 위쪽 글(신호 설명·판단 이유)이 바뀌어 높이가 달라지고, 휴대폰 Safari 는 스크롤 위치를 보정하지 않아
      // 화면이 살짝 밀렸음 → 누른 칸의 화면 위치를 기억했다가 바뀐 만큼 되돌림
      var anchorEl = this, anchorTop = this.getBoundingClientRect().top;
      var keepPlace = function () {
        if (!document.body.contains(anchorEl)) return;
        var d = Math.round(anchorEl.getBoundingClientRect().top - anchorTop), sc = document.getElementById('risk-scroll');
        if (Math.abs(d) >= 1) { if (sc && sc.scrollHeight > sc.clientHeight) sc.scrollTop += d; else window.scrollBy(0, d); }
      };
      setTimeout(function () { keepPlace(); requestAnimationFrame(keepPlace); }, 0);
      var it = cur();
      var kind = $(this).data('kind');
      var on = this.checked;
      if(kind === 'reviewed'){it.controls_reviewed=on;}
      else if (kind === 'none') {
        it.none = on;
        if (on) {                                    // '없음'과 다른 후보는 함께 선택 불가
          $.each(it.curr, function (_, a) { a.checked = false; });
          $('#d-curr-list input[data-kind="curr"]').prop('checked', false);
          if (!$('#d-plan-body').prop('hidden')) renderChecks($('#d-plan-list'), it.plans, 'plan', it);
          else markPlansInUse(it);
        }
      } else {
        var list = kind === 'curr' ? it.curr : it.plans;
        var id = $(this).data('id');
        $.each(list, function (_, a) { if (a.id === id) a.checked = on; });
        if (kind === 'curr' && on && it.none) {
          it.none = false;
          $('#d-curr-list input[data-kind="none"]').prop('checked', false);
        }
        // 현재 조치 중 표시·체크 해제 후 비활성. 현재 조치가 바뀌면 개선대책 후보를 다시 그려 겹친 만큼 새 후보를 보임
        if (kind === 'curr' && !$('#d-plan-body').prop('hidden')) renderChecks($('#d-plan-list'), it.plans, 'plan', it);
        else markPlansInUse(it);
        if (kind === 'plan') it.judged = false;
        // 대책을 처음 고르면 담당자(평가담당자)·예정일(작성일)을 기본값으로 바로 채움
        if (kind === 'plan' && on && applyDefaultOwner(it)) renderOwner(it);   // 기본값 알림은 뺌(화면의 담당자 칸에 바로 보임)
      }
      markDirty();
      if(it.catalog){
        if(kind==='curr' || kind==='none'){it.controls_reviewed = it.none || checkedCount(it.curr) > 0;}
        it.judged=false;renderProjection(it);   // '저장하면 다시 계산' 카드
        $('#d-signal-text').text(SIGNAL_TEXT[it.signal]+' · 마지막 저장 기준(체크 변경 저장 전)');
        if(kind!=='plan')$('#d-reason').text('현재 조치 변경 · 저장 후 재계산 필요');
      }
      $(this).closest('.section').removeClass('is-invalid').find('.js-error').remove();
      renderCounts();
      // 현재 조치·개선대책은 여러 개 고를 수 있어, 하나 체크했다고 다음 블록으로 스크롤하지 않음(강조 표시만 옮김)
      updatePulse(false);
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
      if (kind === 'curr') {it.curr = $.grep(it.curr, function (a) { return a.id !== id; });it.controls_reviewed=it.none || checkedCount(it.curr) > 0;it.judged=false;}
      else { it.plans = $.grep(it.plans, function (a) { return a.id !== id; }); it.judged = false; }
      markDirty();
      renderDetail();
      renderCounts();
    });

    // 일괄 지정에서 변경: 이 항목만 선택된 상태로 일괄 지정 창
    $('#d-owner-btn').on('click', openAssignSingle);
    $('#d-law-open').on('click', openLaw);
    $('#law-modal').appendTo('body');   // 화면 전환 없이 팝업
    $('#assign').appendTo('body');                    // 어느 화면에서든 열 수 있게 (bulk 화면 밖으로)

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
      if (assignSingle) {                          // 이 항목만, 원래 화면 유지
        var it = cur();
        it.owner = { type: type, name: name };
        it.due = due;
        markDirty(state.index);
        SafeT.closeModal();
        renderDetail(); renderCounts();
        SafeT.toast("적용했어요. '입력 내역 저장'을 눌러 저장해 주세요.");
        return;
      }
      var targets = $('#bulk-list input:checked').map(function () { return +this.value; }).get();
      $.each(targets, function (_, i) {             // 선택한 항목은 모두 덮어쓰기
        items[i].owner = { type: type, name: name };
        items[i].due = due;
        markDirty(i);
      });
      SafeT.closeModal(true);
      // 리스트에는 저장 버튼이 없으므로 일괄 지정은 적용 즉시 저장
      saveDraft(bulk.back === 'v-risk' ? 'v-risk' : 'v-list').done(function () { SafeT.toast(targets.length + '건에 지정하고 저장했어요'); });
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
