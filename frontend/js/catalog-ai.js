/* AI 근거·질문 표시. 모델 문장은 text()로만 표시하고 등급은 서버 응답을 사용한다. */
(function($,S){
  'use strict';
  var drafts={};
  function key(item,q){return item+':'+q;}
  function evidence(parent,it){
    var a=it.catalog && it.catalog.ai_analysis;if(!a)return;
    $('<h3>').text('AI가 찾은 위험 후보와 근거').appendTo(parent);
    $('<p>').text(a.rationale).appendTo(parent);
    a.evidence.forEach(function(e){$('<p class="hint">').text(e.media_id+' · '+e.statement).appendTo(parent);});
    $('<p class="hint">').text('모델: '+a.model+' · 사용자 확인 전 후보이며 등급은 공통 기준으로 계산합니다.').appendTo(parent);
    if(it.catalog.scenario.source_refs){
      $('<p class="hint">').text('기준 자료: '+it.catalog.scenario.source_refs.map(function(r){return r.document_id+' '+r.printed_page+'쪽';}).join(', ')).appendTo(parent);
    }
  }
  function summary(doc,submit){
    if(!$('#ai-question-panel').length)$('<section id="ai-question-panel" class="section" aria-live="polite">').insertBefore('#need-box');
    var parent=$('#ai-question-panel').empty(),questions=[];
    doc.items.forEach(function(it){var a=it.catalog && it.catalog.ai_analysis;if(a)a.questions.forEach(function(q){questions.push({item:it.id,q:q});});});
    parent.prop('hidden',!questions.length);if(!questions.length)return;
    $('<h2>').text('추가 확인이 필요해요').appendTo(parent);
    $('<p class="hint">').text('질문에 답한 뒤 현재 조치를 확인해 주세요. 답변 분석 전에는 위험도를 확정하지 않습니다.').appendTo(parent);
    questions.forEach(function(entry,i){
      var q=entry.q,k=key(entry.item,q.id),id='ai-answer-'+i;
      $('<label class="label">').attr('for',id).text(q.text).appendTo(parent);
      $('<textarea class="textarea" maxlength="2000">').attr('id',id).val(drafts[k] || '').on('input',function(){drafts[k]=this.value;}).appendTo(parent);
    });
    $('<button class="btn" type="button">').text('답변 반영').on('click',function(){
      var answers=questions.filter(function(e){return (drafts[key(e.item,e.q.id)] || '').trim();}).map(function(e){return {item_id:e.item,question_id:e.q.id,answer:drafts[key(e.item,e.q.id)].trim()};});
      if(!answers.length){S.toast('답변을 입력해 주세요.');return;}submit(answers);
    }).appendTo(parent);
  }
  S.catalogAI={summary:summary,detail:function(it){if(!$('#ai-evidence').length)$('<section id="ai-evidence" class="section">').insertAfter('#d-reason-box');evidence($('#ai-evidence').empty(),it);},
    readonly:evidence,clear:function(){drafts={};},snapshot:function(){return drafts;},restore:function(x){drafts=x || {};},hasDraft:function(){return Object.keys(drafts).some(function(k){return !!drafts[k];});}};
})(jQuery,window.SafeT);
