/* API 연결 확장. PR #8의 write.js/인증 코드 수정과 겹치지 않도록 분리. */
(function ($, S) {
  'use strict';
  $(function () {
    var photos=[], works=[], busy=false, requestKey=null, lastBody='', reading=0;
    var added=[], catalogs={}, shownWork=null;   // UX-017 이번 평가에만 추가한 기기 [{code|null, nm}] · 업종별 기기 목록 캐시
    var user=S.auth.user() || {};
    var restored=S.auth.takeRestore('assessment-write');
    if(restored && restored.email!==user.email)restored=null;
    $('#work_no').empty().append('<option value="">사업장 불러오는 중</option>');
    $('#eval_dt').val(S.formatDate(S.today())); $('#eval_writer').val(user.name || '');
    $('.name-tags,.photo-grid').empty(); $('.voice-card').remove();
    $('#v-equipment .tag-list,#v-equipment .check-list').empty();
    $('#v-equipment fieldset .hint').text('등록된 기기는 위험 후보 탐색에 참고합니다. 실제 작업·조치 상태는 초안에서 확인해 주세요.');
    $('.disclaimer').text('저장된 입력으로 평가표를 작성합니다. 위험 판단 결과는 현장 검토가 필요합니다.');
    /* UX-016: 등록 기기는 ✓ 칩(모두 포함). 새로 찾은 기기는 칩(체크박스) — 없으면 점선 안내 카드.
       아래 '총 N개' = 등록 기기 + 선택한 새 기기. 서버로 보내는 값은 그대로(등록 기기는 서버가 사업장 기준으로 넣음). */
    var ico=function(n){return S.icon?S.icon(n):'';};
    function regCount(){var w=works.find(function(x){return String(x.work_no)===$('#work_no').val();});return w?w.machines.length:0;}
    function updateSummary(){
      var n=regCount()+added.length+$('#v-equipment .eq-found input[name="ai_machine_nm"]:checked').length;
      $('#eq-summary').text('총 '+n+'개의 기기로 평가표 초안을 생성합니다.');
    }
    function showMachines() {
      var w=works.find(function(x){return String(x.work_no)===$('#work_no').val();});
      var list=$('#v-equipment .tag-list').empty();
      if(w) w.machines.forEach(function(m){$('<li class="eq-chip eq-chip--on">').html(ico('check')).append($('<span>').text(m.machine_nm)).appendTo(list);});
      if(!w || !w.machines.length) $('<li class="hint">등록된 기기가 없습니다.</li>').appendTo(list);
      // 사업장을 바꾸면 업종 기기가 달라질 수 있어 이번 평가에 추가한 기기를 비운다
      var now=w?String(w.work_no):null;
      if(shownWork!==null && now!==shownWork && added.length){added=[];S.toast('사업장이 바뀌어 직접 추가한 기기를 비웠어요.');}
      shownWork=now;renderAdded();
      updateSummary();
    }
    function setDetected(names){
      var box=$('#v-equipment .eq-found .check-list').empty();
      (names || []).forEach(function(nm){
        var l=$('<label class="eq-chip eq-chip--ai">').appendTo(box);
        $('<input type="checkbox" class="sr-only" name="ai_machine_nm" checked>').val(nm).appendTo(l);
        l.append(ico('check').replace('class="ico"','class="ico eq-chip__on"')).append(ico('plus').replace('class="ico"','class="ico eq-chip__off"'));
        $('<span>').text(nm).appendTo(l);
        $('<span class="eq-chip__state">').text(' (추가됨)').appendTo(l);
      });
      var n=(names || []).length;
      $('#v-equipment .js-eq-found-n').text(n);
      $('#v-equipment .eq-found').prop('hidden',!n); $('#v-equipment .eq-empty').prop('hidden',!!n);
      updateSummary();
    }
    $('#v-equipment').on('change','input[name="ai_machine_nm"]',updateSummary);
    S.equipment={setDetected:setDetected};   // 사진 기기 인식 결과를 그릴 때 사용(현재 서버 응답에는 없음)
    /* 기기 추가·변경은 사업장 관리에서. 입력이 있으면 사라진다고 먼저 묻는다. */
    $('#v-equipment').on('click','.js-eq-manage',function(e){
      e.preventDefault();
      var go=function(){S.hasUnsaved=function(){return false;};window.location.href='workplace.html';};
      if(!S.hasUnsaved()){go();return;}
      S.confirm({title:'사업장 관리로 이동할까요?',message:'기기는 사업장 관리에서 추가하거나 바꿀 수 있어요. 지금 이동하면 입력한 사진·음성·글이 사라져요.',ok:'이동',cancel:'계속 작성',danger:true})
        .then(function(yes){if(yes===true)go();});
    });
    /* UX-017 기기 직접 추가: 이번 평가에만 넣는다(사업장 등록 기기는 그대로). 서버가 업종 기기 코드를 검사하고
       같은 이름은 업종 기기로 합친다. 추가한 기기는 위험요인 검색에 등록 기기와 함께 쓰인다. */
    function key(nm){return String(nm||'').replace(/\s+/g,' ').trim().toLowerCase();}
    function currentWork(){return works.find(function(x){return String(x.work_no)===$('#work_no').val();});}
    function isRegistered(code,nm){var w=currentWork();return !!w && w.machines.some(function(m){return (code && m.machine_code===code) || key(m.machine_nm)===key(nm);});}
    function addedIndex(code,nm){for(var i=0;i<added.length;i++){if((code && added[i].code===code) || key(added[i].nm)===key(nm))return i;}return -1;}
    function renderAdded(){
      var list=$('#eq-added-list').empty();
      added.forEach(function(m,i){
        var li=$('<li class="eq-chip eq-chip--added">').appendTo(list);
        li.append(ico('check')).append($('<span>').text(m.nm));
        $('<button type="button" class="eq-chip__x">').attr('aria-label',m.nm+' 빼기').html('<span aria-hidden="true">×</span>')
          .on('click',function(){added.splice(i,1);renderAdded();renderCatalog();updateSummary();$('#eq-added-list .eq-chip__x').first().trigger('focus');}).appendTo(li);
      });
      $('#eq-added').prop('hidden',!added.length);
      $('#eq-add-status').text(added.length?'이번 평가에 추가한 기기 '+added.length+'개':'');
      updateSummary();
    }
    function renderCatalog(){
      var w=currentWork(),box=$('#eq-catalog').empty();
      if(!w){$('<p class="hint">').text('사업장을 먼저 골라 주세요.').appendTo(box);return;}
      var list=catalogs[w.biz_code];
      if(!list){$('<p class="hint">').text('기기 목록을 불러오고 있어요.').appendTo(box);return;}
      var rest=list.filter(function(m){return !isRegistered(m.machine_code,m.machine_nm);});
      if(!rest.length){$('<p class="hint">').text('이 업종 기기는 모두 등록돼 있어요. 아래에 이름을 적어 추가해 주세요.').appendTo(box);return;}
      rest.forEach(function(m){
        var on=addedIndex(m.machine_code,m.machine_nm)>=0;
        $('<button type="button" class="eq-chip eq-chip--pick">').attr('aria-pressed',on?'true':'false')
          .html(ico(on?'check':'plus')).append($('<span>').text(m.machine_nm))
          .on('click',function(){
            var i=addedIndex(m.machine_code,m.machine_nm);
            if(i>=0)added.splice(i,1);else added.push({code:m.machine_code,nm:m.machine_nm});
            renderAdded();renderCatalog();
            $('#eq-catalog .eq-chip--pick').filter(function(){return $(this).text()===m.machine_nm;}).trigger('focus');
          }).appendTo(box);
      });
    }
    function loadCatalog(){
      var w=currentWork();if(!w || catalogs[w.biz_code]){renderCatalog();return;}
      S.api.get('/biz-categories/'+encodeURIComponent(w.biz_code)+'/machines')
        .done(function(list){catalogs[w.biz_code]=list || [];renderCatalog();})
        .fail(function(e){$('#eq-catalog').empty().append($('<p class="hint">').text('기기 목록을 불러오지 못했어요. 이름을 적어 추가할 수 있어요.'));});
    }
    $('#v-equipment').on('click','.js-eq-add',function(e){
      e.preventDefault();
      if(!currentWork()){S.toast('01 기본정보에서 사업장을 먼저 골라 주세요.');return;}
      S.clearError($('#eq-custom'));$('#eq-custom').val('');
      S.openModal('eq-add');loadCatalog();
    });
    $('#eq-custom-btn').on('click',function(){
      var $in=$('#eq-custom'),nm=$in.val().replace(/\s+/g,' ').trim();
      if(!nm){S.fieldError($in,'기기 이름을 입력해 주세요.');$in.trigger('focus');return;}
      if(nm.length>50){S.fieldError($in,'기기 이름은 50자 이내로 입력해 주세요.');return;}
      if(isRegistered(null,nm)){S.fieldError($in,'사업장에 이미 등록된 기기예요.');return;}
      if(addedIndex(null,nm)>=0){S.fieldError($in,'이미 추가한 기기예요.');return;}
      if(added.length>=30){S.fieldError($in,'직접 추가는 30개까지 할 수 있어요.');return;}
      var w=currentWork(),hit=(catalogs[w.biz_code]||[]).find(function(m){return key(m.machine_nm)===key(nm);});
      added.push(hit?{code:hit.machine_code,nm:hit.machine_nm}:{code:null,nm:nm});
      $in.val('');renderAdded();renderCatalog();$('#eq-add-status').text(nm+' 추가 · 이번 평가에 추가한 기기 '+added.length+'개');$in.trigger('focus');
    });
    S.api.get('/workplaces').done(function(data){
      works=data; var sel=$('#work_no').empty().append('<option value="">사업장 선택</option>');
      data.forEach(function(w){$('<option>').val(w.work_no).text(w.workplace+' · '+w.biz_nm).appendTo(sel);});
      if(data.length===1) sel.val(data[0].work_no);
      if(restored)sel.val(restored.work_no);
      if(!data.length) S.toast('사업장을 먼저 등록해 주세요.');
      showMachines();
    }).fail(function(e){$('#work_no').empty();S.fieldError($('#work_no'),e.message);});
    $('#work_no').on('change.assessment',showMachines);
    $('#v-equipment').on('safet:show',showMachines);
    function renderPhotos(){
      var grid=$('.photo-grid').empty();
      /* UX-015: 한 줄 = 썸네일(X) · 파일명(용량) · 삭제, 설명 칸은 파일명 아래 */
      function remove(i){photos.splice(i,1);renderPhotos();}
      function size(b){if(!b)return '';return b>=1048576?(b/1048576).toFixed(1)+'MB':Math.max(1,Math.round(b/1024))+'KB';}
      photos.forEach(function(p,i){
        var li=$('<li class="photo">').appendTo(grid);
        var th=$('<span class="photo__thumb">').appendTo(li);
        $('<img class="photo__img" alt="첨부한 현장 사진">').attr('src',p.data).appendTo(th);
        $('<button type="button" class="photo__remove">×</button>').attr('aria-label','사진 '+(i+1)+' 삭제').on('click',function(){remove(i);}).appendTo(th);
        var info=$('<span class="photo__info">').appendTo(li);
        $('<span class="photo__name">').text(p.name || ('사진 '+(i+1))).attr('title',p.name || '').appendTo(info);
        if(p.size)$('<span class="photo__size">').text('('+size(p.size)+')').appendTo(info);
        $('<label class="sr-only">').attr('for','photo-place-'+i).text('사진 '+(i+1)+' 설명').appendTo(info);
        $('<input class="input photo__place" maxlength="100" placeholder="설명 입력(선택)">')   /* UX-011: 장소 → 설명 (저장 칸은 그대로 place_nm) */.attr('id','photo-place-'+i).val(p.place).on('input',function(){p.place=this.value;}).appendTo(info);
        $('<button type="button" class="photo__del">').html((S.icon?S.icon('trash'):'')+'<span>삭제</span>').attr('aria-label','사진 '+(i+1)+' 삭제').on('click',function(){remove(i);}).appendTo(li);
      });
    }
    // UX-009: '사진 찍기'(#photo-camera)와 '사진 불러오기'(#photo-input) 같은 처리. 화면에 장수 제한은 표시하지 않고,
    // AI 분석이 받는 6장을 넘을 때만 안내(서버·AI 분석 규칙은 그대로)
    $('#photo-input, #photo-camera').off('change').on('change',function(){
      Array.from(this.files || []).forEach(function(file){
        if(photos.length+reading>=6){S.toast('사진은 한 평가표에 6장까지 분석할 수 있어요. 필요 없는 사진을 지운 뒤 추가해 주세요.');return;}
        if(file.size>2*1024*1024 || !/^image\/(jpeg|png|webp)$/.test(file.type)){S.toast('사진은 PNG/JPEG/WebP, 장당 2MB 이하만 올릴 수 있어요.');return;}
        reading++;var reader=new FileReader();
        reader.onload=function(){photos.push({name:file.name.slice(0,100),place:'',data:reader.result,size:file.size});renderPhotos();};
        reader.onerror=function(){S.toast('사진을 읽지 못했어요. 다시 선택해 주세요.');};
        reader.onloadend=function(){reading--;};reader.readAsDataURL(file);
      });this.value='';
    });
    if(restored){
      $('#eval_dt').val(restored.eval_dt);$('#eval_writer').val(restored.eval_writer);
      $('#file_text').val(restored.text || '');
      (restored.members || []).forEach(function(n){$('#member_add').val(n);$('#member-add-btn').trigger('click');});
      photos=(restored.photos || []).filter(function(p){return /^data:image\/(png|jpeg|webp);base64,/.test(p.data);});renderPhotos();
      if(restored.voice_text)$('<div class="field"><label for="voice_text">음성 전사문</label><textarea id="voice_text" class="textarea"></textarea></div>').insertBefore($('#file_text').closest('.field')).find('textarea').val(restored.voice_text);
      requestKey=restored.requestKey;lastBody=restored.lastBody || '';
      added=(restored.added || []).filter(function(m){return m && m.nm;});shownWork=restored.work_no?String(restored.work_no):null;renderAdded();
      S.toast('작성 중인 입력을 복구했어요.');
    }
    S.auth.onExpire(function(){return {page:'assessment-write',data:{email:user.email,work_no:$('#work_no').val(),eval_dt:$('#eval_dt').val(),eval_writer:$('#eval_writer').val(),members:$('[name="member_nm"]').map(function(){return this.value;}).get(),text:$('#file_text').val(),voice_text:$('#voice_text').val(),photos:photos,added:added,requestKey:requestKey,lastBody:lastBody}};});
    var recognition=null;
    $('#voice-btn').off('click').on('click',function(){
      if(!$('#voice_text').length){
        $('<div class="field"><label class="label" for="voice_text">음성 전사문 (직접 수정 가능)</label><textarea id="voice_text" class="textarea" maxlength="10000"></textarea></div>').insertBefore($('#file_text').closest('.field'));
      }
      if(recognition){recognition.stop();return;}
      var Speech=window.SpeechRecognition || window.webkitSpeechRecognition;
      if(!Speech){S.toast('이 브라우저는 음성 인식을 지원하지 않습니다. 전사문을 직접 입력해 주세요.');$('#voice_text').trigger('focus');return;}
      recognition=new Speech();recognition.lang='ko-KR';recognition.interimResults=false;
      recognition.onresult=function(e){$('#voice_text').val(($('#voice_text').val()+' '+e.results[0][0].transcript).trim());};
      recognition.onerror=function(){S.toast('음성 인식에 실패했어요. 다시 시도하거나 글로 입력해 주세요.');};
      recognition.onend=function(){recognition=null;$('#voice-btn').text('음성');};
      recognition.start();$('#voice-btn').text('녹음 종료');
    });
    $('#field-form').on('safet:validate',function(e){if(reading || recognition){e.preventDefault();S.toast('사진 읽기 또는 음성 인식이 끝난 뒤 진행해 주세요.');}});
    S.hasUnsaved=function(){return !busy && !!($('#file_text').val() || photos.length || $('#voice_text').val());};
    $('#v-generating').off('safet:show safet:hide').on('safet:show',function(){
      if(busy)return;
      var d=S.parseDate($('#eval_dt').val());
      if(!d || !$('#work_no').val() || !$('#eval_writer').val().trim()){S.go('v-basic');S.toast('기본정보를 확인해 주세요.');return;}
      var body={work_no:Number($('#work_no').val()),eval_dt:S.formatDate(d).replace(/\./g,'-'),eval_writer:$('#eval_writer').val().trim(),members:$('[name="member_nm"]').map(function(){return this.value;}).get(),text:$('#file_text').val().trim(),voice_text:($('#voice_text').val() || '').trim(),photos:photos.map(function(p){return {name:p.name,place:p.place,data:p.data};}),
        // UX-017 이번 평가에만 추가한 기기. 사진에서 찾아 체크한 기기도 이름으로 함께 보냄
        add_machine_codes:added.filter(function(m){return m.code;}).map(function(m){return m.code;}),
        add_custom_machines:added.filter(function(m){return !m.code;}).map(function(m){return m.nm;})
          .concat($('#v-equipment .eq-found input[name="ai_machine_nm"]:checked').map(function(){return this.value;}).get())};   /* UX-015: 화면용 size 는 보내지 않음(서버 extra 금지) */
      var serial=JSON.stringify(body);if(serial!==lastBody){requestKey=crypto.randomUUID();lastBody=serial;}body.request_key=requestKey;
      busy=true;$('#v-generating .bottom-bar a').attr('aria-disabled','true').hide();
      $('#v-generating .page-title').text('입력을 저장하고 초안을 준비하고 있어요');
      $('#v-generating .ring').text('저장 중').attr('aria-label','저장 중').css('--value','0');
      $('#v-generating progress').attr('hidden',true);  // 실제 진행률을 알 수 없어 막대는 숨기고 회전 표시만 쓴다$('#v-generating .strong,#v-generating .steps-text').text('완료되면 자동으로 초안으로 이동합니다.');
      // 검색·분석에 수십 초가 걸릴 수 있어 멈춘 화면처럼 보이지 않게 회전 표시와 경과 시간을 보여 준다.
      var started=Date.now();
      $('#v-generating .ring').attr('hidden',true);
      $('#gen-spinner').remove();$('<div id="gen-spinner" class="spinner spinner--lg" role="img" aria-label="처리 중">').insertBefore('#v-generating .ring');
      var tick=setInterval(function(){
        var sec=Math.floor((Date.now()-started)/1000);
        // 실제 처리 단계를 알 수 없으므로 단계·남은 시간은 표시하지 않고 경과 시간만 보여 준다(화면설계서 15쪽).
        $('#v-generating .strong').text('위험요인과 대책을 찾고 있어요 · '+sec+'초 경과');
      },1000);
      S.api.post('/evals',body).done(function(r){S.hasUnsaved=function(){return false;};if(S.current)S.current.setEval(r.eval_no);window.location.href=S.current?'draft.html':'draft.html?eval='+r.eval_no;})
      .fail(function(e){S.go('v-equipment');S.toast(e.message+' 입력은 그대로 유지돼요.');})
      .always(function(){clearInterval(tick);$('#gen-spinner').remove();$('#v-generating .ring,#v-generating progress').removeAttr('hidden');busy=false;$('#v-generating .bottom-bar a').removeAttr('aria-disabled').show();});
    });
    window.addEventListener('beforeunload',function(e){if(S.hasUnsaved()){e.preventDefault();e.returnValue='';}});
  });
})(jQuery,window.SafeT);
