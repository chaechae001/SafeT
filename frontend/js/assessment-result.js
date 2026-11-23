/* 확정 문서 조회: 서버 저장값만 표시, 편집 입력 없음. */
(function($,S){
  'use strict';
  var labels={R:'상 · 즉시 개선',Y:'중 · 개선 필요',G:'하 · 유지 관리',N:'판단 필요'}, doc, index=0;
  function signal(value){return $('<span class="signal" role="img"><i></i><i></i><i></i></span>').attr({'data-signal':value,'aria-label':'위험 신호 '+labels[value]});}
  // 대책 끝의 반복 꼬리말("— 미실시·미흡 부분 개선")은 화면에서만 숨김(초안 화면과 같게, 저장 값은 그대로)
  function clean(t){return String(t||'').replace(/\s*—\s*미실시·미흡 부분 개선$/,'');}
  function selected(a){return a.filter(function(x){return x.checked;}).map(function(x){return clean(x.text);}).join(' · ');}
  /** 예상 위험도 요약 카드(초안 상세와 같은 모양): 현재 → 개선 후 예상, 남은 필수 조치, 안내 2줄, ⓘ 계산 설명 */
  var NAME={R:'상',Y:'중',G:'하',N:'판단 전'};
  function light(sig){return $('<span class="signal" role="img"><i></i><i></i><i></i></span>').attr({'data-signal':sig||'N','aria-label':'위험도 '+NAME[sig||'N']});}
  function projection(parent,it){
    var card=$('<section class="proj-card">').appendTo(parent), head=$('<div class="proj-card__head">').appendTo(card);
    $('<h2 class="proj-card__title">예상 위험도 분석</h2>').appendTo(head);
    if(!it.judged){$('<p class="proj-card__muted">').text('예상 위험도를 계산하지 않은 항목이에요.').appendTo(card);return;}
    var pr=it.catalog&&it.catalog.projected_result, controls=it.catalog&&it.catalog.scenario&&it.catalog.scenario.controls;
    var row=$('<div class="proj-card__row">').appendTo(card);
    function side(label,sig){return $('<span class="proj-card__side">').append($('<span class="proj-card__label">').text(label),light(sig),$('<b class="proj-card__grade">').attr('data-signal',sig).text(NAME[sig]||''));}
    row.append(side('현재',it.signal||'N'),$('<span class="proj-card__arrow" aria-hidden="true">→</span>'),side('개선 후 예상',it.after||'N'));
    var ps=pr&&S.riskText&&S.riskText.parse?S.riskText.parse(pr.reason,controls):null, tip='';
    if(ps&&ps.core.length&&ps.next)tip="'"+ps.core[0]+"'"+(ps.core.length>1?' 외 '+(ps.core.length-1)+'개':'')+' 추가 시 '+S.riskText.ro(ps.next)+' 완화 가능';
    // '꼭 필요한 조치 ○○가 아직 남아 있어요' 코멘트는 숨김(초안 상세와 같게)
    else if(ps&&ps.keep)tip="남은 조치를 해도 위험의 크기 때문에 '"+ps.keep+"' 유지";
    var info=$('<button type="button" class="proj-card__info" aria-expanded="false" aria-label="계산 설명">').html(S.icon?S.icon('info'):'i').appendTo(head);
    if(tip)$('<p class="proj-card__tip">').html(S.icon?S.icon('bulb'):'').append($('<span>').text(tip)).appendTo(card);
    $('<ul class="proj-card__notes"><li>선택한 대책 모두 이행 시 예상되는 예측치입니다(실제 결과 아님).</li><li>최종 안전 판단 및 관리는 담당자가 확인·수행합니다.</li></ul>').appendTo(card);
    if(pr&&pr.reason) $('<p class="proj-card__detail">').text(S.riskText?S.riskText.friendly(pr.reason,controls):pr.reason).appendTo(card);
    var full = card.children(".proj-card__tip, .proj-card__notes, .proj-card__detail").prop("hidden", true);
    info.on('click',function(){var open=full.prop('hidden');full.prop('hidden',!open);info.attr('aria-expanded',open?'true':'false');});
  }
  function para(parent,label,value){$('<p>').append($('<b>').text(label+' ')).append(document.createTextNode(value || '미입력')).appendTo(parent);}
  function checkedList(parent,label,actions){
    var section=$('<section class="section">').appendTo(parent);
    $('<h2 class="section-title">').text(label).appendTo(section);
    var list=$('<ul class="readonly-list">').appendTo(section);
    actions.filter(function(a){return a.checked;}).forEach(function(a){$('<li>').text(clean(a.text)).appendTo(list);});
  }
  function detail(){
    var it=doc.items[index], page=$('#v-detail .page').empty();
    $('<p class="eyebrow">').text('위험 '+(index+1)+' / '+doc.items.length+' · 읽기 전용').appendTo(page);
    $('<h1 class="page-title">').text(it.job).appendTo(page);
    var box=$('<section class="risk-box">').appendTo(page);$('<div class="risk-box__head">').append(signal(it.signal),$('<span>').text(labels[it.signal])).appendTo(box);
    if(it.type)$('<span class="tag">').text(it.type).appendTo(box);
    para(box,'위험요인',it.title);para(box,'원인',it.cause);para(box,'판단 이유',S.riskText?S.riskText.friendly(it.reason,it.catalog&&it.catalog.scenario&&it.catalog.scenario.controls):it.reason);   /* 쉬운 말 */
    if(S.catalogAI)S.catalogAI.readonly(page,it);
    if(it.law){para(box,'법령',it.law.name);para(box,'요지',it.law.summary);}
    if(it.assessment_mode==='input_based' && !it.curr.length)para(page,'현재 안전조치','입력에서 확인되지 않음');
    else if(it.none)para(page,'현재 조치','현재 조치 없음');else checkedList(page,'현재 안전조치',it.curr);
    if(it.keep==='Y')para(page,'개선대책','현재 상태 유지');else checkedList(page,'개선대책 계획',it.plans);
    if(it.owner)para(page,'담당·예정',it.owner.name+' · '+it.due);
    // '개선 후 예상 신호' + 판단 이유와 똑같이 반복되던 '예상 판정 근거' → 요약 카드 하나
    if(it.keep!=='Y')projection(page,it);
    // '위험도 정책'(내부 정책 이름)은 화면에 표시하지 않음
    $('#result-prev').prop('disabled',index===0);$('#result-next').prop('disabled',index===doc.items.length-1);
  }
  $(function(){
    var no=Number(new URLSearchParams(location.search).get('eval')) || (S.current && S.current.evalNo());
    if(no && S.current)S.current.setEval(no);
    $('#v-list .page,#v-detail .page').empty();
    var nav=$('#v-detail .bottom-bar').empty();
    $('<button class="btn" id="result-prev">이전 항목</button>').on('click',function(){index--;detail();}).appendTo(nav);
    $('<a class="btn" href="#v-list">목록</a>').appendTo(nav);
    $('<button class="btn" id="result-next">다음 항목</button>').on('click',function(){index++;detail();}).appendTo(nav);
    if(!no){$('#v-list .page').text('내 평가표에서 문서를 선택해 주세요.');return;}
    S.api.get('/evals/'+no).done(function(r){
      doc=r;if(r.eval_status==='W'){location.replace(S.current?'draft.html':'draft.html?eval='+no);return;}
      // 제목 아래 [확정] + [🔒 확정된 평가표 · 읽기 전용 (수정 불가)] 배지 한 줄, 기본 정보는 연회색 요약 상자 2열
      var page=$('#v-list .page'),head=$('<div class="result-head">').appendTo(page);
      $('<h1 class="page-title">').text(r.eval_nm).appendTo(head);
      $('<div class="result-badges">').append(
        $('<span class="tag status" data-status="C">확정</span>'),
        $('<span class="lock-pill">').html((S.icon?S.icon('lock'):'')+'<span>확정된 평가표 · 읽기 전용 (수정 불가)</span>')
      ).appendTo(head);
      var meta=$('<dl class="result-summary">').appendTo(page);
      // 확정일은 초 없이 'YYYY-MM-DD HH:MM'
      [['사업장',r.workplace],['평가일',r.eval_dt.slice(0,10)],['작성자',r.eval_writer],['위험 항목',r.items.length+'건'],['참여자',r.members.join(', ') || '등록 없음'],['확정일',(r.confirm_dt || '').replace('T',' ').slice(0,16)]].forEach(function(pair){
        $('<div>').append($('<dt>').text(pair[0]),$('<dd>').text(pair[1])).appendTo(meta);
      });
      if(r.assessment_mode==='input_based' && r.result_status==='partial')
        $('<p class="notice">').text('일부 검색 후보는 기준에 연결되지 않아 제외했습니다. 표시된 항목은 연결 가능한 위험만 포함합니다.').appendTo(page);
      var list=$('<ol class="card-list">').appendTo(page);
      r.items.forEach(function(it,i){
        var card=$('<a class="card result-item" href="#v-detail">').on('click',function(){index=i;detail();});
        card.append($('<span class="card__head">').append($('<span class="card__title">').text((i+1)+' '+it.job),signal(it.signal)));
        // 왼쪽 작은 회색 라벨 열 | 오른쪽 내용, 담당·예정은 얇은 구분선 아래
        var rows=$('<dl class="result-rows">').appendTo(card);
        function row(parent,label,value){$('<div>').append($('<dt>').text(label),$('<dd>').text(value || '미입력')).appendTo(parent);}
        row(rows,'위험요인',it.title);
        row(rows,'현재 조치',it.none?'현재 조치 없음':it.assessment_mode==='input_based' && !it.curr.length?'입력에서 확인되지 않음':selected(it.curr));
        row(rows,'개선대책',it.keep==='Y'?'현재 상태 유지':selected(it.plans));
        if(it.owner)row($('<dl class="result-rows result-rows--owner">').appendTo(card),'담당·예정',it.owner.name+' · '+it.due);
        $('<li>').append(card).appendTo(list);
      });
      // '현장 검토가 필요한' → 확정 상태와 헷갈리지 않는 문구
      $('.disclaimer').text(r.generation_source==='demo'?'개발 시험용 합성 평가표 · 실제 현장 판정에 사용하지 마세요.':'확정된 평가표예요 · 최종 안전 판단은 담당자가 해요.');
      // 다음 할 일(서명)을 화면 안에서 바로. 서명이 끝났으면 결과 공유. 내 평가표는 위쪽 '‹ 내 평가표'
      var bar=$('#v-list .bottom-bar').empty();
      $('<button class="btn" type="button" data-report="">').html((S.icon?S.icon('download'):'')+'문서 다운로드').appendTo(bar);
      if(r.eval_status==='S'||r.eval_status==='A')$('<a class="btn btn--primary" href="share.html">결과 공유</a>').appendTo(bar);
      else $('<a class="btn btn--primary" href="sign.html">').html((S.icon?S.icon('sign'):'')+'서명하기').appendTo(bar);
      $('<a class="btn btn--sm result-back" href="home.html"><span aria-hidden="true">‹</span> 내 평가표</a>').prependTo(page);
      if(r.items.length)detail();S.go('v-list');
    }).fail(function(e){$('#v-list .page').text(e.message);});
  });
})(jQuery,window.SafeT);
