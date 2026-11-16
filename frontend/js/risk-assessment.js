/* Shared restaurant risk evidence/questions UI. All model/user text uses text(), never HTML. */
(function ($, S) {
  'use strict';
  var drafts = {}, additional = '';
  var status = {confirmed:'판정', provisional:'잠정 판정', candidate:'위험 후보', needs_information:'추가 확인 필요', closed:'사고 경로 종료', not_applicable:'해당 없음'};
  function p(parent, label, value) { $('<p>').append($('<b>').text(label+' ')).append(document.createTextNode(value || '미확인')).appendTo(parent); }
  function title(result, stale) {
    if(stale)return '조치 변경 · 재판정 필요';
    return (status[result.status] || '확인 필요') + (result.grade ? ' · '+result.grade : '');
  }
  function summary(parent, doc, submit) {
    parent.empty(); if(!doc.risk_assessment){parent.prop('hidden',true);return;}
    parent.prop('hidden',false);
    var report=doc.risk_assessment, analysis=report.analysis, stale=doc.risk_needs_reassessment;
    $('<h2 class="section-title">입력 근거와 추가 확인</h2>').appendTo(parent);
    p(parent,'평가 범위',analysis.scope);
    p(parent,'현재 상태',stale?'안전조치가 변경되어 재판정이 필요합니다.':('확인된 최고 등급 '+(report.summary.max_confirmed || '미확정')+' / 잠정 최고 등급 '+(report.summary.max_provisional || '없음')));
    $('<p class="hint">확인하지 않은 장소·작업은 안전하다고 판단하지 않습니다. 추가 답변과 현장 검토 후 확정하세요.</p>').appendTo(parent);
    if(!submit)return;
    var form=$('<form class="stack risk-questions">').appendTo(parent);
    var qs=analysis.questions.slice().sort(function(a,b){return a.priority-b.priority;});
    var overflow=null;
    qs.forEach(function(q,i){
      if(i===5)overflow=$('<details class="disclosure"><summary>나머지 확인 질문</summary></details>').appendTo(form);
      var field=$('<div class="field">').appendTo(overflow || form), id='risk-q-'+i;
      $('<label class="label">').attr('for',id).text(q.question).appendTo(field);
      $('<p class="hint">').text(q.decision_impact).appendTo(field);
      $('<textarea class="textarea" maxlength="2000">').attr('id',id).val(drafts[q.id] || '').on('input',function(){drafts[q.id]=this.value;}).appendTo(field);
      $('<p class="hint">').text(q.safe_verification).appendTo(field);
    });
    if(!qs.length)$('<p>추가 질문이 없습니다. 변경된 작업·조치를 아래에 입력해 다시 판단할 수 있습니다.</p>').appendTo(form);
    $('<label class="label" for="risk-additional">추가 관찰·변경된 내용</label>').appendTo(form);
    $('<textarea class="textarea" id="risk-additional" maxlength="10000">').val(additional).on('input',function(){additional=this.value;}).appendTo(form);
    $('<button class="btn btn--primary" type="submit">답변 반영 · 다시 판단</button>').appendTo(form);
    form.on('submit',function(e){
      e.preventDefault();
      var answers=qs.filter(function(q){return (drafts[q.id] || '').trim();}).map(function(q){return {question_id:q.id,answer:drafts[q.id].trim()};});
      submit(answers,additional.trim());
    });
  }
  function detail(parent, item, doc) {
    parent.empty();if(!item.risk){parent.prop('hidden',true);return;}
    parent.prop('hidden',false);
    var h=item.risk.hazard,r=item.risk.result,stale=item.risk.stale || doc.risk_needs_reassessment;
    $('<h2 class="section-title">').text(title(r,stale)).appendTo(parent);
    if(r.immediate_exposure_stop && !stale)$('<p class="notice notice--danger">급박한 위험이 확인되었습니다. 위험 노출을 중단하고 현장 책임자에게 알려 주세요.</p>').appendTo(parent);
    p(parent,'사고 경로',h.exposure+' → '+h.event+' → '+h.consequence);
    p(parent,'판정 근거',h.rationale);
    p(parent,'피해·조치 후보','S'+h.severity_options.join('/S')+' · C'+h.control_options.join('/C'));
    if(r.status==='provisional')p(parent,'범위',({1:'하',2:'중',3:'상'}[r.range.min])+' ~ '+({1:'하',2:'중',3:'상'}[r.range.max])+' · 미확인을 미설치로 단정한 결과가 아닙니다.');
    var ev=doc.risk_assessment.analysis.evidence.filter(function(e){return h.evidence_ids.indexOf(e.id)!==-1;});
    var evidence=$('<details class="disclosure"><summary>입력 근거 확인</summary></details>').appendTo(parent);
    ev.forEach(function(e){p(evidence,e.kind==='observed'?'관찰':'보고·기록·추론',e.statement+' ['+e.media_id+']');});
    h.controls.forEach(function(c){p(evidence,c.name,({verified_effective:'유효 확인',reported_effective:'사용자 보고',ineffective:'무효',absent:'없음',unknown:'미확인',not_applicable:'해당 없음'}[c.state])+(c.critical?' · 핵심 조치':''));});
    if(h.uncertainty.length)p(parent,'미확인',h.uncertainty.join(' · '));
    if(h.contradictions.length)p(parent,'상충 정보',h.contradictions.join(' · '));
    p(parent,'자료 근거',h.source_refs.map(function(s){return s.document_id+' 인쇄 '+s.printed_page+'쪽(PDF '+s.pdf_page+'쪽)';}).join(', '));
    p(parent,'자료 이름','A: 쉽고 간편한 위험성평가 / B: 서비스업 재해사례 / C: 음식및숙박업 실무길잡이');
  }
  S.riskUI={summary:summary,detail:detail,title:title,clear:function(){drafts={};additional='';},hasDraft:function(){return !!additional || Object.keys(drafts).some(function(k){return !!drafts[k];});},snapshot:function(){return {answers:drafts,additional:additional};},restore:function(v){if(v){drafts=v.answers || {};additional=v.additional || '';}}};
})(jQuery,window.SafeT);
