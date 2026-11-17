/* API 연결 확장. PR #8의 write.js/인증 코드 수정과 겹치지 않도록 분리. */
(function ($, S) {
  'use strict';
  $(function () {
    var photos=[], works=[], busy=false, requestKey=null, lastBody='', reading=0;
    var user=S.auth.user() || {};
    var restored=S.auth.takeRestore('assessment-write');
    if(restored && restored.email!==user.email)restored=null;
    $('#work_no').empty().append('<option value="">사업장 불러오는 중</option>');
    $('#eval_dt').val(S.formatDate(S.today())); $('#eval_writer').val(user.name || '');
    $('.name-tags,.photo-grid').empty(); $('.voice-card').remove();
    $('#v-equipment .tag-list,#v-equipment .check-list').empty();
    $('#v-equipment fieldset .hint').text('등록된 기기는 위험요인 탐색에 참고합니다. 실제 가동·작업 여부는 현장 입력으로 확인합니다.');
    $('.disclaimer').text('저장된 입력으로 평가표를 작성합니다. 위험 판단 결과는 현장 검토가 필요합니다.');
    function showMachines() {
      var w=works.find(function(x){return String(x.work_no)===$('#work_no').val();});
      var list=$('#v-equipment .tag-list').empty();
      if(w) w.machines.forEach(function(m){$('<li class="tag tag--primary">').text(m.machine_nm).appendTo(list);});
      if(!w || !w.machines.length) $('<li class="hint">등록된 기기가 없습니다.</li>').appendTo(list);
    }
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
      photos.forEach(function(p,i){
        var li=$('<li class="photo">').appendTo(grid);
        $('<img class="photo__img" alt="첨부한 현장 사진">').attr('src',p.data).appendTo(li);
        $('<button type="button" class="photo__remove">×</button>').attr('aria-label','사진 '+(i+1)+' 삭제').on('click',function(){photos.splice(i,1);renderPhotos();}).appendTo(li);
        $('<label class="sr-only">').attr('for','photo-place-'+i).text('사진 '+(i+1)+' 장소').appendTo(li);
        $('<input class="input" maxlength="100" placeholder="장소 입력">').attr('id','photo-place-'+i).val(p.place).on('input',function(){p.place=this.value;}).appendTo(li);
      });
    }
    $('#photo-input').off('change').on('change',function(){
      Array.from(this.files || []).forEach(function(file){
        if(photos.length+reading>=6 || file.size>2*1024*1024 || !/^image\/(jpeg|png|webp)$/.test(file.type)){S.toast('사진은 PNG/JPEG/WebP, 장당 2MB 이하, 최대 6장입니다.');return;}
        reading++;var reader=new FileReader();
        reader.onload=function(){photos.push({name:file.name.slice(0,100),place:'',data:reader.result});renderPhotos();};
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
      S.toast('작성 중인 입력을 복구했어요.');
    }
    S.auth.onExpire(function(){return {page:'assessment-write',data:{email:user.email,work_no:$('#work_no').val(),eval_dt:$('#eval_dt').val(),eval_writer:$('#eval_writer').val(),members:$('[name="member_nm"]').map(function(){return this.value;}).get(),text:$('#file_text').val(),voice_text:$('#voice_text').val(),photos:photos,requestKey:requestKey,lastBody:lastBody}};});
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
      var body={work_no:Number($('#work_no').val()),eval_dt:S.formatDate(d).replace(/\./g,'-'),eval_writer:$('#eval_writer').val().trim(),members:$('[name="member_nm"]').map(function(){return this.value;}).get(),text:$('#file_text').val().trim(),voice_text:($('#voice_text').val() || '').trim(),photos:photos};
      var serial=JSON.stringify(body);if(serial!==lastBody){requestKey=crypto.randomUUID();lastBody=serial;}body.request_key=requestKey;
      busy=true;$('#v-generating .bottom-bar a').attr('aria-disabled','true').hide();
      $('#v-generating .page-title').text('입력을 저장하고 초안을 준비하고 있어요');
      $('#v-generating .ring').text('저장 중').attr('aria-label','저장 중').css('--value','0');
      $('#v-generating progress').removeAttr('value');$('#v-generating .strong,#v-generating .steps-text').text('완료되면 자동으로 초안으로 이동합니다.');
      S.api.post('/evals',body).done(function(r){S.hasUnsaved=function(){return false;};if(S.current)S.current.setEval(r.eval_no);window.location.href=S.current?'draft.html':'draft.html?eval='+r.eval_no;})
      .fail(function(e){S.go('v-equipment');S.toast(e.message+' 입력은 그대로 유지돼요.');})
      .always(function(){busy=false;$('#v-generating .bottom-bar a').removeAttr('aria-disabled').show();});
    });
    window.addEventListener('beforeunload',function(e){if(S.hasUnsaved()){e.preventDefault();e.returnValue='';}});
  });
})(jQuery,window.SafeT);
