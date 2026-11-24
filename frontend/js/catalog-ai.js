/* AI 근거·질문 표시. 모델 문장은 text()로만 표시하고 등급은 서버 응답을 사용한다. */
(function($,S){
  'use strict';
  var drafts={};
  function key(item,q){return item+':'+q;}
  function documents(parent,it){
    if(!it.authoring)return;
    var state=it.authoring, docs=it.document_evidence || [];
    var box=$('<section class="rag-evidence" aria-label="검색 문헌 근거">').appendTo(parent);
    $('<h3>').text('검색 문헌 근거').appendTo(box);
    $('<p class="hint">').text('위험 후보를 찾는 데 참고한 문헌입니다. 실제 현장 상태나 안전조치의 실시 여부를 뜻하지 않습니다.').appendTo(box);
    if(!docs.length)$('<p>').text('연결된 검색 문헌 없음 · 카탈로그 기준으로 작성된 항목입니다.').appendTo(box);
    (state.row.document_summaries || []).forEach(function(group){
      var card=$('<div class="rag-source">').appendTo(box);
      $('<p class="rag-summary">').text(group.summary).appendTo(card);
      if(group.prevention_summary)$('<p class="rag-prevention">').text('문헌의 예방대책: '+group.prevention_summary).appendTo(card);
      if(group.reference_notice)$('<p class="rag-citation">').text(group.reference_notice).appendTo(card);
      $('<p class="rag-application">').text('이 내용을 현재 평가 항목의 위험 후보 선정 근거로 사용했습니다.').appendTo(card);
      var title=group.source_file.split(/[\\/]/).pop().replace(/\.pdf$/i,'').replace(/^최종보고서_/,'').replace(/_/g,' ');
      $('<p class="rag-citation">').text('출처: '+title+' · PDF '+group.pdf_pages.join(', ')+'쪽').appendTo(card);
      var details=$('<details class="rag-originals">').appendTo(card);
      $('<summary>').text('원문·세부 출처 펼쳐보기').appendTo(details);
      group.entries.forEach(function(s){
        $('<blockquote>').text(s.hazard_text).appendTo(details);
        if(s.prevention_text)$('<blockquote>').text(s.prevention_text).appendTo(details);
        $('<p class="rag-citation">').text('PDF '+(s.pdf_pages || []).join(', ')+'쪽 · 출처 '+s.source_id+' · 연결 '+s.link_id).appendTo(details);
      });
    });
    $('<p class="hint">').text('문헌 버전: '+(state.data_version || '연결 없음')+(state.context_version ? ' + '+state.context_version : '')).appendTo(box);
  }
  function evidence(parent,it){
    if(it.authoring){
      $('<h3>').text('입력에서 확인한 내용').appendTo(parent);
      it.authoring.row.evidence.forEach(function(e){$('<p>').text(e.statement).appendTo(parent);});
      var unknown=it.authoring.row.control_evidence.filter(function(e){return e.state==='unknown';}).length;
      $('<p class="hint">').text('현재 안전조치 '+unknown+'개 미확인 · 미실시로 단정하지 않습니다.').appendTo(parent);
      documents(parent,it);
      return;
    }
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
    if(!$('#rag-status-panel').length)$('<section id="rag-status-panel" class="section" aria-live="polite">').insertBefore('#need-box');
    var rag=$('#rag-status-panel').empty().prop('hidden',doc.assessment_mode!=='input_based');
    if(doc.assessment_mode==='input_based'){
      $('<h2>').text('위험성평가표 작성 결과').appendTo(rag);
      var pendingOnly = !doc.items.length && ((doc.review_candidates || []).length || (doc.unmatched_risks || []).length);
      if(pendingOnly) $('<p>').text('작업 근거가 확인된 평가 항목이 없어 검토 후보만 초안으로 보관합니다.').appendTo(rag);
      else $('<p>').text('입력 내용과 검색 문헌을 바탕으로 작성했습니다. 각 위험 항목에서 근거 문장과 출처를 볼 수 있습니다.').appendTo(rag);
      if(!pendingOnly && (doc.review_candidates || []).length){
        $('<p class="hint">').text('현장에서 하지 않는 작업만 제외해 주세요. 실제 작업이거나 작업 여부가 미확인인 후보는 평가를 마칠 때까지 확정을 보류합니다.').appendTo(rag);
      }
      (doc.review_candidates || []).forEach(function(c){
        if(pendingOnly){
          $('<p>').text(c.scenario_id+' · '+(c.reason==='input_denies_work'?'입력에서 작업 미사용':'작업 미확인')).appendTo(rag);
          return;
        }
        var label=$('<label>').appendTo(rag);
        $('<input type="checkbox" class="candidate-exclusion">').val(c.scenario_id).prop('checked',(doc.excluded_review_candidates || []).includes(c.scenario_id)).appendTo(label);
        label.append(document.createTextNode(' '+c.scenario_id+' · '+(c.reason==='input_denies_work'?'입력에서 작업 미사용':'작업 미확인')+' · 현장 비적용으로 제외'));
      });
      if((doc.unmatched_risks || []).length){
        $('<p class="hint">').text('다음 위험은 기준 연결을 확인해야 합니다.').appendTo(rag);
        (doc.unmatched_risks || []).forEach(function(x){$('<p class="hint">').text(x.replace('RAG 시나리오 매핑 없음: EQ_FRYER:gas','튀김기 가스 위험: 기준 연결 미확인').replace('RAG 시나리오 매핑 없음: EQ_FRYER:respiratory','튀김기 호흡기 위험: 기준 연결 미확인')).appendTo(rag);});
      }
    }
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
