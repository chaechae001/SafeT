/* DB 연결 근거와 추가 확인. 모델·사용자 문자열은 text()로 표시한다. */
(function($,S){
  'use strict';
  var drafts={},additional='';
  function p(parent,label,value){$('<p>').append($('<b>').text(label+' ')).append(document.createTextNode(value || '미확인')).appendTo(parent);}
  function summary(parent,doc,submit){
    parent.empty().prop('hidden',!doc.risk_assessment);if(!doc.risk_assessment)return;
    $('<h2 class="section-title">입력 근거와 추가 확인</h2>').appendTo(parent);
    p(parent,'평가 범위','입력된 작업과 DB 시나리오 · 미관찰 영역의 안전은 미확인');
    if(doc.risk_assessment.report.unmatched_observations.length)p(parent,'추가 현장 검토가 필요한 관찰',doc.risk_assessment.report.unmatched_observations.join(' · '));
    if(!submit)return;
    var qs=doc.risk_assessment.questions, form=$('<form class="stack">').appendTo(parent);
    var overflow=null;
    qs.forEach(function(q,i){
      if(i===5)overflow=$('<details class="disclosure"><summary>나머지 확인 질문</summary></details>').appendTo(form);
      var field=$('<div class="field">').appendTo(overflow || form),id='risk-q-'+i;
      $('<label class="label">').attr('for',id).text(q.question).appendTo(field);
      $('<textarea class="textarea" maxlength="2000">').attr('id',id).val(drafts[q.id] || '').on('input',function(){drafts[q.id]=this.value;}).appendTo(field);
    });
    $('<label class="label" for="risk-additional">추가 관찰·변경 내용</label>').appendTo(form);
    $('<textarea class="textarea" id="risk-additional" maxlength="10000">').val(additional).on('input',function(){additional=this.value;}).appendTo(form);
    $('<button class="btn btn--primary" type="submit">답변 반영 · 다시 확인</button>').appendTo(form);
    form.on('submit',function(e){e.preventDefault();submit(qs.filter(function(q){return (drafts[q.id] || '').trim();}).map(function(q){return {question_id:q.id,answer:drafts[q.id].trim()};}),additional.trim());});
  }
  function detail(parent,it){
    var cs=it.catalog,ai=cs && cs.ai;parent.empty().prop('hidden',!ai);if(!ai)return;
    $('<h2 class="section-title">위험요인과 입력 근거</h2>').appendTo(parent);
    p(parent,'시나리오',cs.scenario.title);
    p(parent,'현재 위험도',cs.current_result.reason);
    p(parent,'적용 확인',ai.match.applicability==='confirmed'?'입력 근거에 연결됨 · 현장 담당자 검토 필요':'실제 작업 여부 미확인');
    var box=$('<details class="disclosure"><summary>근거·미확인·출처 확인</summary></details>').appendTo(parent);
    ai.evidence.forEach(function(e){p(box,e.kind==='observed'?'사진 관찰':'사용자 보고',e.statement+' ['+e.media_id+']');});
    cs.scenario.controls.forEach(function(c){if(ai.unknown_ids.indexOf(c.id)!==-1)p(box,'미확인',c.current_text);});
    ai.match.uncertainties.forEach(function(v){p(box,'추가 확인',v);});
    p(box,'자료 근거',cs.scenario.source_refs.map(function(r){return r.document_id+' 인쇄 '+r.printed_page+'쪽(PDF '+r.pdf_page+'쪽)';}).join(' · '));
    p(box,'자료 이름','A: 쉽고 간편한 위험성평가 / B: 서비스업 재해사례 / C: 음식및숙박업 실무길잡이');
  }
  S.riskUI={summary:summary,detail:detail,clear:function(){drafts={};additional='';},hasDraft:function(){return !!additional || Object.keys(drafts).some(function(k){return !!drafts[k];});},snapshot:function(){return {answers:drafts,additional:additional};},restore:function(v){if(v){drafts=v.answers || {};additional=v.additional || '';}}};
})(jQuery,window.SafeT);
