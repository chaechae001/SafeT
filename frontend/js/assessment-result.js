/* 확정 문서 조회: 서버 저장값만 표시, 편집 입력 없음. */
(function($,S){
  'use strict';
  var labels={R:'상 · 즉시 개선',Y:'중 · 개선 필요',G:'하 · 유지 관리',N:'판단 필요'}, doc, index=0;
  function signal(value){return $('<span class="signal" role="img"><i></i><i></i><i></i></span>').attr({'data-signal':value,'aria-label':'위험 신호 '+labels[value]});}
  function selected(a){return a.filter(function(x){return x.checked;}).map(function(x){return x.text;}).join(' · ');}
  function para(parent,label,value){$('<p>').append($('<b>').text(label+' ')).append(document.createTextNode(value || '미입력')).appendTo(parent);}
  function checkedList(parent,label,actions){
    var section=$('<section class="section">').appendTo(parent);
    $('<h2 class="section-title">').text(label).appendTo(section);
    var list=$('<ul class="readonly-list">').appendTo(section);
    actions.filter(function(a){return a.checked;}).forEach(function(a){$('<li>').text(a.text).appendTo(list);});
  }
  /* 확정 시 담당자가 현장 비적용으로 제외한 검토 후보. 항목마다 같은 기록이 있어 후보 ID 기준으로 한 번만 표시한다. */
  function excluded(parent,items){
    var seen={},rows=[];
    items.forEach(function(it){
      var review=it.work_review;if(!review)return;
      (review.excluded_details || (review.excluded_candidates || []).map(function(id){return {scenario_id:id,task:id};})).forEach(function(c){
        if(seen[c.scenario_id])return;seen[c.scenario_id]=true;rows.push(c);
      });
    });
    if(!rows.length)return;
    var box=$('<section class="section excluded-candidates" aria-label="검토 후 제외한 작업">').appendTo(parent);
    $('<h2 class="section-title">').text('검토 후 제외한 작업').appendTo(box);
    $('<p class="hint">').text('검색 후보였으나 담당자가 이 현장에 해당하지 않는다고 확인한 작업입니다. 위험이 낮다는 뜻이 아닙니다.').appendTo(box);
    var list=$('<ul class="readonly-list">').appendTo(box);
    rows.forEach(function(c){
      var why=c.reason==='input_denies_work'?' (입력에서 작업 미사용)':c.reason==='work_unconfirmed'?' (입력에서 작업 미확인)':'';
      $('<li>').text(c.task+' · 현장 비적용'+why).appendTo(list);
    });
  }
  function detail(){
    var it=doc.items[index], page=$('#v-detail .page').empty();
    $('<p class="eyebrow">').text('위험 '+(index+1)+' / '+doc.items.length+' · 읽기 전용').appendTo(page);
    $('<h1 class="page-title">').text(it.job).appendTo(page);
    var box=$('<section class="risk-box">').appendTo(page);$('<div class="risk-box__head">').append(signal(it.signal),$('<span>').text(labels[it.signal])).appendTo(box);
    if(it.type)$('<span class="tag">').text(it.type).appendTo(box);
    para(box,'위험요인',it.title);para(box,'원인',it.cause);para(box,'판단 이유',it.reason);
    if(S.catalogAI)S.catalogAI.readonly(page,it);
    if(it.law){para(box,'법령',it.law.name);para(box,'요지',it.law.summary);}
    if(it.assessment_mode==='input_based' && S.catalogAI && it.authoring && it.authoring.row.control_details){
      var current=$('<section class="section">').appendTo(page);
      $('<h2 class="section-title">').text('현재 안전조치 · 입력 근거').appendTo(current);
      S.catalogAI.controls(current,it);
    }
    else if(it.assessment_mode==='input_based' && !it.curr.length)para(page,'현재 안전조치','입력에서 확인되지 않음');
    else if(it.none)para(page,'현재 조치','현재 조치 없음');else checkedList(page,'현재 안전조치',it.curr);
    if(it.keep==='Y')para(page,'개선대책','현재 상태 유지');else checkedList(page,'개선대책 계획',it.plans);
    if(it.owner)para(page,'담당·예정',it.owner.name+' · '+it.due);
    para(page,'개선 후 예상 신호',it.judged?labels[it.after]+' (계획 단계의 예상, 실제 결과 아님)':'판단 필요 · 예상 신호 미산정');
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
      var page=$('#v-list .page'),head=$('<div class="row row--wrap">').appendTo(page);
      $('<h1 class="page-title">').text(r.eval_nm).appendTo(head);
      $('<span class="tag status" data-status="C">확정</span>').appendTo(head);
      var meta=$('<dl class="kv">').appendTo(page);
      [['사업장',r.workplace],['평가일',r.eval_dt.slice(0,10)],['작성자',r.eval_writer],['위험 항목',r.items.length+'건'],['참여자',r.members.join(', ') || '등록 없음'],['확정일',(r.confirm_dt || '').replace('T',' ')]].forEach(function(pair){
        $('<dt>').text(pair[0]).appendTo(meta);$('<dd>').text(pair[1]).appendTo(meta);
      });
      $('<p class="hint">확정된 평가표 · 읽기 전용 · 수정할 수 없어요.</p>').appendTo(page);
      if(r.assessment_mode==='input_based' && r.result_status==='partial')
        $('<p class="notice">').text('일부 검색 후보는 기준에 연결되지 않아 제외했습니다. 표시된 항목은 연결 가능한 위험만 포함합니다.').appendTo(page);
      var list=$('<ol class="card-list">').appendTo(page);
      r.items.forEach(function(it,i){
        var card=$('<a class="card result-item" href="#v-detail">').on('click',function(){index=i;detail();});
        card.append($('<span class="card__head">').append($('<span class="card__title">').text((i+1)+' '+it.job),signal(it.signal)));
        para(card,'위험요인',it.title);para(card,'현재 조치',it.none?'현재 조치 없음':it.assessment_mode==='input_based' && !it.curr.length?'입력에서 확인되지 않음':selected(it.curr));
        para(card,'개선대책',it.keep==='Y'?'현재 상태 유지':selected(it.plans));
        if(it.owner)para(card,'담당·예정',it.owner.name+' · '+it.due);
        $('<li>').append(card).appendTo(list);
      });
      if(r.assessment_mode==='input_based')excluded(page,r.items);
      $('.disclaimer').text(r.generation_source==='demo'?'개발 시험용 합성 평가표 · 실제 현장 판정에 사용하지 마세요.':'현장 검토가 필요한 평가표입니다.');
      if(r.items.length)detail();S.go('v-list');
    }).fail(function(e){$('#v-list .page').text(e.message);});
  });
})(jQuery,window.SafeT);
