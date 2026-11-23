/* API 연결 확장. PR #8의 write.js/인증 코드 수정과 겹치지 않도록 분리. */
(function ($, S) {
  'use strict';
  $(function () {
    var photos=[], works=[], worksReady=false, busy=false, requestKey=null, lastBody='', reading=0;
    var added=[], catalogs={}, shownWork=null;   // UX-017 이번 평가에만 추가한 기기 [{code|null, nm}] · 업종별 기기 목록 캐시
    var user=S.auth.user() || {};
    var restored=S.auth.takeRestore('assessment-write');
    if(restored && restored.email!==user.email)restored=null;
    /* UX-023: 작성 중 자동 보관. 휴대폰에서 카메라·사진 앱을 다녀오거나 브라우저가 페이지를 다시 불러오면 입력이 사라져
       처음부터 다시 써야 했음 → 입력이 바뀔 때마다 이 탭(sessionStorage)에 보관하고, 다시 열리면 보던 단계와 함께 되살림.
       초안이 만들어지면 지움. 같은 계정·12시간 안의 보관본만 사용. 사진이 저장 한도를 넘으면 사진만 빼고 보관 */
    var AUTO_KEY='safet.write.autosave', autoRestored=false;
    if(!restored){
      try{
        var a=JSON.parse(sessionStorage.getItem(AUTO_KEY)||'null');
        if(a && a.email===user.email && Date.now()-a.at<12*3600*1000){
          // 기존 보관본에는 사업장을 직접 골랐는지 구분하는 값이 없다.
          var chosenWork=a.work_touched===undefined ? !!a.work_no : a.work_touched;
          var basicEdited=chosenWork || a.eval_dt_auto===false || (a.eval_writer && a.eval_writer!==user.name);
          if(basicEdited || a.text || a.voice_text || (a.photos||[]).length || (a.members||[]).length || (a.added||[]).length || (a.found||[]).length){
            restored=a;autoRestored=true;
          }
        }
      }catch(e){}
    }
    $('#work_no').empty().append('<option value="">사업장 불러오는 중</option>');
    $('#eval_dt').val(S.formatDate(S.today())); $('#eval_writer').val(user.name || '');
    $('.name-tags,.photo-grid').empty(); $('.voice-card').remove();
    $('#v-equipment .tag-list,#v-equipment .check-list').empty();
    /* UX-018: 이 안내는 '사진에서 새로 찾은 기기' 제목 아래가 아니라 등록 기기 상자 아래에 둔다(같은 문구). */
    $('#v-equipment .eq-new > .hint').prop('hidden',true);
    if(!$('#eq-reg-hint').length)$('<p class="hint eq-reg__hint" id="eq-reg-hint">').text('등록된 기기는 위험 후보 탐색에 참고합니다. 실제 작업·조치 상태는 초안에서 확인해 주세요.').appendTo('#v-equipment .eq-reg');
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
      if (!worksReady) return;
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
    /** names: ['기기명'] 또는 UX-025 자동 보관 복원용 [{nm, on}] (on=false 면 체크 해제 상태로) */
    function setDetected(names){
      var box=$('#v-equipment .eq-found .check-list').empty();
      (names || []).forEach(function(x){
        var nm=typeof x==='string'?x:x.nm, on=typeof x==='string'?true:x.on!==false;
        var l=$('<label class="eq-chip eq-chip--ai">').appendTo(box);
        $('<input type="checkbox" class="sr-only" name="ai_machine_nm">').prop('checked',on).val(nm).appendTo(l);
        l.append(ico('check').replace('class="ico"','class="ico eq-chip__on"')).append(ico('plus').replace('class="ico"','class="ico eq-chip__off"'));
        $('<span>').text(nm).appendTo(l);
        $('<span class="eq-chip__state">').text(' (추가됨)').appendTo(l);
      });
      var n=(names || []).length;
      $('#v-equipment .js-eq-found-n').text(n);
      $('#v-equipment .eq-found').prop('hidden',!n); $('#v-equipment .eq-empty').prop('hidden',!!n);
      $('#v-equipment .eq-new > .hint').prop('hidden',!n);   // 찾은 기기가 있을 때만 '매장에 있는 것만 체크' 안내
      updateSummary();
    }
    $('#v-equipment').on('change','input[name="ai_machine_nm"]',updateSummary);
    S.equipment={setDetected:setDetected};   // 사진 기기 인식 결과를 그릴 때 사용(현재 서버 응답에는 없음)
    $('#v-equipment').on('click','.js-eq-manage',function(e){
      e.preventDefault();
      var href=this.href;
      function go(){
        if(reading){S.toast('사진을 처리한 뒤 다시 눌러 주세요.');return;}
        var data=snapshot();
        data.view='#v-equipment';
        try{sessionStorage.setItem(AUTO_KEY,JSON.stringify(data));}
        catch(err){S.toast('작성 내용을 보관할 공간이 부족해요. 사진 수를 줄인 뒤 다시 시도해 주세요.');return;}
        clearTimeout(autoTimer);
        autoOff=true;
        S.hasUnsaved=function(){return false;};
        window.location.href=href;
      }
      if($('#recorder .recorder__audio').attr('src')){
        S.confirm({title:'사업장 관리로 이동할까요?',message:'음성 전사문은 보관됩니다. 녹음 원본은 이동하면 다시 들을 수 없어요.',ok:'이동',cancel:'계속 작성'})
          .then(function(yes){if(yes===true)go();});
      }else{go();}
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
      works=data; worksReady=true; var sel=$('#work_no').empty().append('<option value="">사업장 선택</option>');
      data.forEach(function(w){$('<option>').val(w.work_no).text(w.workplace+' · '+w.biz_nm).appendTo(sel);});
      if(data.length===1) sel.val(data[0].work_no);
      if(restored)sel.val(restored.work_no);
      if(!data.length) S.toast('사업장을 먼저 등록해 주세요.');
      showMachines();
    }).fail(function(e){$('#work_no').empty();S.fieldError($('#work_no'),e.message);});
    var workTouched=!!(restored && (restored.work_touched===undefined ? restored.work_no : restored.work_touched));
    $('#work_no').on('change.assessment',function(){workTouched=true;showMachines();});
    $('#v-equipment').on('safet:show',showMachines);
    function renderPhotos(){
      var grid=$('.photo-grid').empty();
      /* UX-015: 한 줄 = 썸네일(X) · 파일명(용량) · 삭제, 설명 칸은 파일명 아래 */
      function remove(i){photos.splice(i,1);renderPhotos();if(typeof autosave==="function")autosave();}
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
    /** UX-022: 휴대폰 사진(보통 3~10MB, iPhone HEIC 포함)도 그대로 고를 수 있게, 올리기 전에 이 기기에서 줄임.
        긴 변 1600px JPEG(품질 0.85)로 바꾸고, 그래도 서버 한도(사진당 약 2MB)를 넘으면 크기·품질을 단계적으로 더 낮춤.
        원본 파일은 보내지 않음. 브라우저가 읽지 못하는 형식이면 안내만 함 */
    var MAX_DATA=2700000;   // 서버 Photo.data 최대 2,800,000자보다 조금 작게
    function shrink(file){
      var d=$.Deferred(), url=URL.createObjectURL(file), img=new Image();
      img.onload=function(){
        URL.revokeObjectURL(url);
        var side=1600, q=0.85, out='';
        for(var k=0;k<6;k++){
          var sc=Math.min(1, side/Math.max(img.naturalWidth, img.naturalHeight)), c=document.createElement('canvas');
          c.width=Math.max(1,Math.round(img.naturalWidth*sc)); c.height=Math.max(1,Math.round(img.naturalHeight*sc));
          var g=c.getContext('2d'); g.fillStyle='#fff'; g.fillRect(0,0,c.width,c.height); g.drawImage(img,0,0,c.width,c.height);
          out=c.toDataURL('image/jpeg', q);
          if(out.length<=MAX_DATA) break;
          side=Math.round(side*0.8); q=Math.max(0.6, q-0.05);
        }
        if(out.length<=MAX_DATA && /^data:image\/jpeg;base64,/.test(out)) d.resolve(out); else d.reject();
      };
      img.onerror=function(){URL.revokeObjectURL(url);d.reject();};
      img.src=url;
      return d.promise();
    }
    $('#photo-input, #photo-camera').off('change').on('change',function(){
      Array.from(this.files || []).forEach(function(file){
        if(photos.length+reading>=6){S.toast('사진은 한 평가표에 6장까지 분석할 수 있어요. 필요 없는 사진을 지운 뒤 추가해 주세요.');return;}
        if(file.type && !/^image\//.test(file.type)){S.toast('사진 파일만 올릴 수 있어요.');return;}
        reading++;
        shrink(file).done(function(data){
          var nm=file.name.replace(/\.[^.]+$/,'')+'.jpg';
          photos.push({name:nm.slice(0,100),place:'',data:data,size:Math.round(data.length*0.75)});renderPhotos();autosave();
        }).fail(function(){S.toast('사진을 읽지 못했어요. 다른 사진을 고르거나 사진 찍기를 이용해 주세요.');})
          .always(function(){reading--;});
      });this.value='';
    });
    // UX-025: 작성자가 평가일을 직접 바꿨는지(바꾸지 않았으면 다시 열 때 그날 날짜로). 자정을 넘겨 다시 저장해도 '직접 바꿈'으로 오인하지 않게 값 비교 대신 입력으로 판단
    var dtTouched=false;
    $('#eval_dt').on('input change',function(e){if(e.originalEvent || e.isTrigger)dtTouched=true;});
    if(restored){
      // UX-025: 평가일은 작성자가 직접 바꾼 경우만 되살림. 기본값(그날 날짜)이었으면 오늘 날짜를 그대로 둠
      //         (23:30에 쓰다 00:10에 다시 열면 전날 날짜가 남던 문제). 예전 보관본(eval_dt_auto 없음)도 같은 규칙
      if(restored.eval_dt_auto===false){$('#eval_dt').val(restored.eval_dt);dtTouched=true;}
      $('#eval_writer').val(restored.eval_writer);
      $('#file_text').val(restored.text || '');
      (restored.members || []).forEach(function(n){$('#member_add').val(n);$('#member-add-btn').trigger('click');});
      photos=(restored.photos || []).filter(function(p){return /^data:image\/(png|jpeg|webp);base64,/.test(p.data);});renderPhotos();
      if(restored.voice_text)$('<div class="field"><label for="voice_text">음성 전사문</label><textarea id="voice_text" class="textarea"></textarea></div>').insertBefore($('#file_text').closest('.field')).find('textarea').val(restored.voice_text);
      requestKey=restored.requestKey;lastBody=restored.bodyDigest || restored.lastBody || '';
      added=(restored.added || []).filter(function(m){return m && m.nm;});shownWork=restored.work_no?String(restored.work_no):null;renderAdded();
      // UX-025: '사업장에도 저장' 체크와 사진에서 찾은 기기의 체크 상태도 되살림
      if(restored.save_workplace)$('#eq-save-workplace').prop('checked',true);
      if((restored.found || []).length)setDetected(restored.found);
      if(autoRestored)showRestoreNote();
      else S.toast('작성 중인 입력을 복구했어요.');
      if(autoRestored && /^#v-(field|equipment)$/.test(restored.view || '')){var v=restored.view.slice(1);setTimeout(function(){S.go(v);},0);}
    }
    /* UX-025 자동 보관 항목 추가: eval_dt_auto(평가일이 그날 기본값인지), save_workplace('사업장에도 저장' 체크), found(사진에서 찾은 기기와 체크 상태) */
    function foundState(){return $('#v-equipment .eq-found input[name="ai_machine_nm"]').map(function(){return {nm:this.value,on:this.checked};}).get();}
    function snapshot(){
      // 목록 조회 전·실패 시 빈 선택값이 이전 사업장을 덮어쓰지 않게 한다.
      var workNo=worksReady ? $('#work_no').val() : (restored && restored.work_no);
      return {email:user.email,at:Date.now(),view:location.hash,work_touched:workTouched,work_no:workNo,eval_dt:$('#eval_dt').val(),eval_dt_auto:!dtTouched,eval_writer:$('#eval_writer').val(),save_workplace:$('#eq-save-workplace').prop('checked'),found:foundState(),members:$('[name="member_nm"]').map(function(){return this.value;}).get(),text:$('#file_text').val(),voice_text:$('#voice_text').val(),photos:photos,added:added,requestKey:requestKey,bodyDigest:/^[0-9a-f]{64}$/.test(lastBody)?lastBody:''};}
    var autoTimer=null, autoOff=false;
    function autosave(){
      if(autoOff)return;
      clearTimeout(autoTimer);
      autoTimer=setTimeout(function(){
        if(autoOff)return;
        var d=snapshot();
        try{sessionStorage.setItem(AUTO_KEY,JSON.stringify(d));}
        catch(e){try{d.photos=[];sessionStorage.setItem(AUTO_KEY,JSON.stringify(d));}catch(e2){}}
      },400);
    }
    function clearAutosave(){autoOff=true;clearTimeout(autoTimer);try{sessionStorage.removeItem(AUTO_KEY);}catch(e){}}
    /* UX-025: 자동 보관본을 불러오면 화면 위에 안내 + '새로 쓰기'(불러온 내용을 버리고 빈 작성 화면으로). 보는 단계마다 맨 위로 옮김 */
    function showRestoreNote(){
      var $n=$('<div class="notice notice--muted restore-note" id="restore-note" role="status">')
        .append($('<span class="restore-note__text">').text('작성하던 내용을 불러왔어요.'))
        .append($('<button type="button" class="btn btn--sm restore-note__reset">새로 쓰기</button>'));
      function place(){var $p=$('.view.is-active .page').first();if($p.length)$n.prependTo($p);}
      $('#v-basic, #v-field, #v-equipment').on('safet:show',place);place();
      $n.on('click','.restore-note__reset',function(){
        S.confirm({title:'불러온 내용을 지우고 새로 쓸까요?',message:'사진·글·참여자·기기 선택이 모두 지워져요.',ok:'새로 쓰기',cancel:'취소',danger:true})
          .then(function(yes){if(yes!==true)return;clearAutosave();S.hasUnsaved=function(){return false;};window.location.replace('write.html');});
      });
    }
    $(document).on('input change','#v-basic, #v-field, #v-equipment',autosave);
    $(document).on('click','#member-add-btn, .name-tags, .photo-grid, #eq-added',function(){setTimeout(autosave,50);});
    $(window).on('hashchange',autosave);
    $(document).on('visibilitychange',function(){if(document.visibilityState==='hidden'){clearTimeout(autoTimer);if(!autoOff){var d=snapshot();try{sessionStorage.setItem(AUTO_KEY,JSON.stringify(d));}catch(e){try{d.photos=[];sessionStorage.setItem(AUTO_KEY,JSON.stringify(d));}catch(e2){}}}}});
    S.auth.onExpire(function(){return {page:'assessment-write',data:snapshot()};});
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
    $('#v-generating').off('safet:show safet:hide').on('safet:show',async function(){
      if(busy)return;
      var d=S.parseDate($('#eval_dt').val());
      if(!d || !$('#work_no').val() || !$('#eval_writer').val().trim()){S.go('v-basic');S.toast('기본정보를 확인해 주세요.');return;}
      var body={work_no:Number($('#work_no').val()),eval_dt:S.formatDate(d).replace(/\./g,'-'),eval_writer:$('#eval_writer').val().trim(),members:$('[name="member_nm"]').map(function(){return this.value;}).get(),text:$('#file_text').val().trim(),voice_text:($('#voice_text').val() || '').trim(),photos:photos.map(function(p){return {name:p.name,place:p.place,data:p.data};}),
        // UX-017 이번 평가에만 추가한 기기. 사진에서 찾아 체크한 기기도 이름으로 함께 보냄
        add_machine_codes:added.filter(function(m){return m.code;}).map(function(m){return m.code;}),
        add_custom_machines:added.filter(function(m){return !m.code;}).map(function(m){return m.nm;})
          .concat($('#v-equipment .eq-found input[name="ai_machine_nm"]:checked').map(function(){return this.value;}).get())};
      if(added.length && $('#eq-save-workplace').prop('checked'))body.save_machines_to_workplace=true;   // UX-018   /* UX-015: 화면용 size 는 보내지 않음(서버 extra 금지) */
      busy=true;
      try {
        var serial=JSON.stringify(body);
        var bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(serial));
        var digest=Array.from(new Uint8Array(bytes),function(x){return x.toString(16).padStart(2,'0');}).join('');
        if(!requestKey || (lastBody!==digest && lastBody!==serial)) requestKey=crypto.randomUUID();
        lastBody=digest;
        body.request_key=requestKey;
        autosave();
      } catch(err) {
        busy=false;S.go('v-equipment');S.toast('요청을 준비하지 못했어요. 다시 시도해 주세요.');return;
      }
      $('#v-generating .bottom-bar a').attr('aria-disabled','true').hide();
      /* UX-022: 초안 생성 화면. 서버는 한 번의 요청으로 처리해 실제 진행률을 알 수 없으므로 % 숫자·단계 완료·남은 시간은 보이지 않는다(화면설계서 15쪽).
         막대는 경과 시간에 따라 90%까지 점점 느려지며 부드럽게 차오르고, 실제로 끝났을 때만 100%로 채운 뒤 초안으로 이동한다. */
      var $scr=$('#v-generating .progress-screen').addClass('gen'), started=Date.now(), raf=0, shown=0;
      $scr.children().attr('hidden',true);
      $('#gen-ui').remove();
      var $ui=$('<div id="gen-ui" class="gen__ui">').appendTo($scr);
      // UX-023: 막대 대신 도넛. 바깥 원(진행)이 부드럽게 차오르고, 안쪽 빛 띠가 천천히 돎. 가운데 문서 아이콘
      var R=52, C=2*Math.PI*R;
      var $bar=$('<div class="gen__donut" role="progressbar" aria-label="초안 만드는 중" aria-valuetext="진행 중">'+
        '<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="gen__track" cx="60" cy="60" r="'+R+'"/>'+
        '<circle class="gen__arc" cx="60" cy="60" r="'+R+'" stroke-dasharray="'+C.toFixed(1)+'" stroke-dashoffset="'+C.toFixed(1)+'"/></svg>'+
        '<span class="gen__spin" aria-hidden="true"></span><span class="gen__doc" aria-hidden="true"></span></div>').appendTo($ui);
      $('<h1 class="page-title gen__title">초안을 만들고 있어요</h1>').appendTo($ui);
      $('<p class="gen__desc">입력한 작업과 기기를 바탕으로<br>위험요인·관련 법령·개선대책을 찾고 있어요.</p>').appendTo($ui);
      var $arc=$bar.find('.gen__arc');
      var setPct=function(v){$arc.attr('stroke-dashoffset',(C*(1-v/100)).toFixed(2));};
      var $time=$('<p class="gen__time" aria-live="off">0초 경과</p>').appendTo($ui);
      $('<p class="gen__note">화면을 닫지 마세요. 끝나면 초안 화면으로 자동 이동해요.</p>').appendTo($ui);
      function frame(){
        var t=(Date.now()-started)/1000, target=90*(1-Math.exp(-t/14));   // 14초에 약 57%, 30초에 약 79%, 이후 90%에 가까워짐
        shown+= (target-shown)*0.08; setPct(shown); $bar.attr('data-pct',shown.toFixed(1));
        raf=requestAnimationFrame(frame);
      }
      raf=requestAnimationFrame(frame);
      var tick=setInterval(function(){$time.text(Math.floor((Date.now()-started)/1000)+'초 경과');},1000);
      function cleanup(){cancelAnimationFrame(raf);clearInterval(tick);}
      S.api.post('/evals',body).done(function(r){
        S.hasUnsaved=function(){return false;};clearAutosave();if(S.current)S.current.setEval(r.eval_no);
        cleanup();$bar.addClass('is-done').attr('aria-valuetext','완료');setPct(100);$time.text('초안을 만들었어요. 이동할게요.');
        setTimeout(function(){window.location.href=S.current?'draft.html':'draft.html?eval='+r.eval_no;}, S.reduceMotion?0:350);
      })
      .fail(function(e){
        cleanup();$('#gen-ui').remove();$scr.removeClass('gen').children().removeAttr('hidden');
        $('#v-generating .bottom-bar a').removeAttr('aria-disabled').show();
        S.go('v-equipment');S.toast(e.message+' 입력은 그대로 유지돼요.');
      })
      .always(function(){busy=false;});
    });
    window.addEventListener('beforeunload',function(e){if(S.hasUnsaved()){e.preventDefault();e.returnValue='';}});
  });
})(jQuery,window.SafeT);
