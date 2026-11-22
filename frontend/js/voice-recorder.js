/* =========================================================
   음성 녹음기 (write.html 02 현장) · UX-006 → UX-009 → UX-013 → UX-015 (2026-11-22)
   상태 3단계(+일시정지)
   ① 대기   : [● 녹음] [■ 중지(비활성)] ············ [↻ 초기화]
   ② 녹음 중: 카드 오른쪽 위 '● 00:18 녹음 중' · [⏸ 일시정지] [■ 중지(빨강)] · 초기화 비활성
              글 칸 위 '실시간 변환 중...' + 음파 아이콘, 변환 중인 문장에 커서
   ③ 완료   : '⏱ 00:24 녹음 완료' · [▶] 재생 막대 00:00 / 00:24 · [재녹음] [초기화]
              글 칸 위 '변환된 텍스트 (터치하여 수정 가능)'
   - 말한 내용은 글 칸(#voice_text)에 적힘(고칠 수 있음). 시간 제한 없음
   - 녹음 파일은 이 화면에서 다시 듣기만 하고 서버로 보내지 않음(평가표에는 글만 저장 · 기존과 같음)
   ========================================================= */
(function ($, S) {
  'use strict';

  function fmt(sec) { sec = Math.max(0, Math.floor(sec || 0)); return ('0' + Math.floor(sec / 60)).slice(-2) + ':' + ('0' + (sec % 60)).slice(-2); }
  function ico(n) { return S.icon ? S.icon(n) : ''; }

  $(function () {
    if (!$('#voice-btn').length) return;
    var st = { state: 'idle', sec: 0, timer: null, rec: null, media: null, stream: null, chunks: [], url: null, wantRec: false };
    var Speech = window.SpeechRecognition || window.webkitSpeechRecognition;

    function ensureUI() {
      var $slot = $('#voice-slot');
      if (!$('#voice_text').length) {
        $('<div class="field"><label class="sr-only" for="voice_text">음성 전사문</label><textarea id="voice_text" class="textarea" maxlength="10000" placeholder="녹음하면 여기에 글로 적혀요"></textarea></div>').appendTo($slot.length ? $slot : $('#blk-voice'));
      } else if ($slot.length && !$slot.find('#voice_text').length) {
        $('#voice_text').closest('.field').appendTo($slot);
      }
      if ($('#recorder').length) return;
      var $r = $('<section class="recorder" id="recorder" aria-label="음성 녹음">');
      var $row = $('<div class="recorder__row">').appendTo($r);
      $('<button type="button" class="rec-chip rec-start"><span class="rec-dot" aria-hidden="true"></span><span class="rec-start__text">녹음</span></button>').appendTo($row);
      $('<button type="button" class="rec-chip rec-pause" hidden><span class="rec-pause__bars" aria-hidden="true"></span><span class="rec-pause__text">일시정지</span></button>').appendTo($row);
      $('<button type="button" class="rec-chip rec-stop" disabled><span class="rec-square" aria-hidden="true"></span>중지</button>').appendTo($row);
      // 완료 상태: 재생기(▶ + 막대 + 시간)
      var $pl = $('<div class="rec-player" hidden>').appendTo($row);
      $('<button type="button" class="rec-play" aria-label="녹음 다시 듣기"><span class="rec-play__ico" aria-hidden="true"></span></button>').appendTo($pl);
      $('<span class="rec-player__track"><span class="rec-player__bar"><i></i></span><span class="rec-player__time">00:00 / 00:00</span></span>').appendTo($pl);
      var $right = $('<span class="recorder__right">').appendTo($row);
      $('<button type="button" class="rec-link rec-redo" hidden>' + ico('mic') + '재녹음</button>').appendTo($right);
      $('<button type="button" class="rec-link rec-reset" disabled>' + ico('reset') + '초기화</button>').appendTo($right);
      $('<audio class="recorder__audio" preload="metadata" hidden></audio>').appendTo($r);
      $('<p class="recorder__msg" role="alert" hidden></p>').appendTo($r);
      $('<span class="sr-only recorder__status" role="status"></span>').appendTo($r);
      $r.prependTo($('#voice-slot').length ? $('#voice-slot') : $('#blk-voice'));
      // 글 칸 위 안내 줄 + 실시간 변환 문장
      var $f = $('#voice_text').closest('.field').addClass('voice-box');
      if (!$f.find('.voice-box__head').length) {
        $('<div class="voice-box__head"><span class="voice-box__label"></span><span class="voice-box__wave" aria-hidden="true">' + ico('wave') + '</span></div>').prependTo($f);
        $('<p class="voice-box__live" aria-live="polite" hidden><span class="voice-box__interim"></span><span class="voice-caret" aria-hidden="true">|</span></p>').insertAfter($f.find('textarea'));
      }
      setState('idle');
    }

    function hasText() { return !!$.trim($('#voice_text').val() || ''); }

    function setState(s, msg) {
      st.state = s;
      var rec = s === 'rec', paused = s === 'paused', live = rec || paused, done = s === 'done';
      var $r = $('#recorder');
      $r.attr('data-state', s);
      $('#blk-voice').attr('data-rec', s);
      $r.find('.rec-start').prop('hidden', live || done);
      $r.find('.rec-pause').prop('hidden', !live).find('.rec-pause__text').text(paused ? '계속' : '일시정지');
      $r.find('.rec-pause').toggleClass('is-paused', paused);
      $r.find('.rec-stop').prop('hidden', done).prop('disabled', !live);
      $r.find('.rec-player').prop('hidden', !(done && st.url));
      $r.find('.rec-redo').prop('hidden', !done);
      $r.find('.rec-reset').prop('disabled', live || (!st.url && !hasText()));
      // 오른쪽 위 상태
      var $s = $('#rec-status');
      if (live) $s.html('<i class="rec-status__dot" aria-hidden="true"></i><span class="rec-status__time">' + fmt(st.sec) + '</span> ' + (paused ? '일시정지' : '녹음 중'));
      else if (done) $s.html(ico('timer') + '<span class="rec-status__time">' + fmt(st.sec) + '</span> 녹음 완료');
      $s.attr('data-state', s).prop('hidden', !(live || done));
      // 글 칸 위 안내
      var $f = $('#voice_text').closest('.voice-box');
      $f.attr('data-state', s).toggleClass('is-empty', !hasText());
      $f.find('.voice-box__label').text(rec ? '실시간 변환 중...' : paused ? '일시정지 중' : done ? '변환된 텍스트 (터치하여 수정 가능)' : '');
      $f.find('.voice-box__head').prop('hidden', !(live || done));
      $f.find('.voice-box__wave').prop('hidden', !rec);
      if (!rec) $f.find('.voice-box__live').prop('hidden', true);
      updatePlayer();
      $r.find('.recorder__status').text({ idle: '녹음 대기', rec: '녹음 중', paused: '일시정지', done: '녹음 완료' }[s]);
      $r.find('.recorder__msg').text(msg || '').prop('hidden', !msg);
      $('#voice-btn').text(rec ? '녹음 종료' : '음성');
    }

    function tick() { $('#rec-status .rec-status__time').text(fmt(st.sec)); }
    function startTimer() { clearInterval(st.timer); st.timer = setInterval(function () { st.sec += 1; tick(); }, 1000); }

    function startRecognition() {
      if (!Speech) return;
      var r = new Speech();
      r.lang = 'ko-KR'; r.continuous = true; r.interimResults = true;
      r.onresult = function (e) {
        var interim = '';
        for (var i = e.resultIndex; i < e.results.length; i++) {
          var t = e.results[i][0].transcript;
          if (e.results[i].isFinal) $('#voice_text').val(($('#voice_text').val() + ' ' + t).trim()).trigger('input');
          else interim += t;
        }
        $('.voice-box__interim').text(interim);
        $('.voice-box__live').prop('hidden', !interim);
      };
      r.onerror = function (e) {
        if (e.error === 'no-speech' || e.error === 'aborted') return;
        st.wantRec = false;
        $('#recorder .recorder__msg').text('글로 바꾸지 못했어요. 직접 입력해 주세요.').prop('hidden', false);
      };
      r.onend = function () {
        $('.voice-box__live').prop('hidden', true);
        if (st.wantRec && st.state === 'rec') { try { r.start(); } catch (err) { /* 무시 */ } }
      };
      st.rec = r;
      try { r.start(); } catch (err) { st.rec = null; }
    }
    function stopRecognition() { if (st.rec) { var r = st.rec; st.rec = null; try { r.stop(); } catch (err) { /* 무시 */ } } }

    function start() {
      ensureUI();
      if (st.state === 'rec' || st.state === 'paused') return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        if (!Speech) { setState(st.state, '이 브라우저는 녹음을 지원하지 않아요. 글로 입력해 주세요.'); return; }
        begin(null);
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(begin).catch(function () {
        setState(st.url ? 'done' : 'idle', '마이크를 쓸 수 없어요. 마이크를 허용하거나 글로 입력해 주세요.');
      });
    }

    function begin(stream) {
      st.stream = stream; st.sec = 0; st.chunks = []; st.wantRec = true;
      if (stream && window.MediaRecorder) {
        try {
          st.media = new MediaRecorder(stream);
          st.media.ondataavailable = function (e) { if (e.data && e.data.size) st.chunks.push(e.data); };
          st.media.onstop = function () {
            if (st.url) URL.revokeObjectURL(st.url);
            st.url = st.chunks.length ? URL.createObjectURL(new Blob(st.chunks, { type: (st.media && st.media.mimeType) || 'audio/webm' })) : null;
            $('#recorder .recorder__audio').attr('src', st.url || '');
            if (st.state === 'done') setState('done');
          };
          st.media.start(1000);
        } catch (err) { st.media = null; }
      }
      setState('rec', Speech ? null : '이 브라우저는 글로 바꾸지 못해요. 녹음 후 직접 입력해 주세요.');
      startRecognition();
      startTimer();
    }

    function pauseToggle() {
      if (st.state === 'rec') {
        clearInterval(st.timer); st.timer = null; st.wantRec = false; stopRecognition();
        if (st.media && st.media.state === 'recording' && st.media.pause) { try { st.media.pause(); } catch (err) { /* 무시 */ } }
        setState('paused');
      } else if (st.state === 'paused') {
        if (st.media && st.media.state === 'paused' && st.media.resume) { try { st.media.resume(); } catch (err) { /* 무시 */ } }
        st.wantRec = true; setState('rec'); startRecognition(); startTimer();
      }
    }

    function stop() {
      if (st.state !== 'rec' && st.state !== 'paused') return;
      st.wantRec = false;
      clearInterval(st.timer); st.timer = null;
      stopRecognition();
      setState('done');
      if (st.media && st.media.state !== 'inactive') { try { st.media.stop(); } catch (err) { /* 무시 */ } }
      if (st.stream) st.stream.getTracks().forEach(function (t) { t.stop(); });
      st.stream = null;
    }

    function clearAll() {
      var a = $('#recorder .recorder__audio')[0]; if (a) { a.pause(); }
      if (st.url) URL.revokeObjectURL(st.url);
      st.url = null; st.sec = 0;
      $('#recorder .recorder__audio').attr('src', '');
      $('#voice_text').val('').trigger('input');
    }

    function reset() {
      S.confirm({ title: '녹음을 초기화할까요?', message: '녹음과 음성 글이 지워져요.', ok: '초기화', cancel: '취소', danger: true })
        .then(function (yes) { if (yes !== true) return; clearAll(); setState('idle'); });
    }
    function redo() {
      S.confirm({ title: '다시 녹음할까요?', message: '지금 녹음과 음성 글이 지워지고 새로 녹음해요.', ok: '재녹음', cancel: '취소' })
        .then(function (yes) { if (yes !== true) return; clearAll(); setState('idle'); start(); });
    }

    /* 재생기: ▶/❚❚ + 막대 + 00:00 / 00:24 (길이는 녹음한 시간 기준) */
    function updatePlayer() {
      var a = $('#recorder .recorder__audio')[0]; if (!a) return;
      var total = isFinite(a.duration) && a.duration > 0 ? a.duration : st.sec;
      var cur = a.currentTime || 0;
      $('#recorder .rec-player__time').text(fmt(cur) + ' / ' + fmt(total));
      $('#recorder .rec-player__bar i').css('width', total ? Math.min(100, cur / total * 100) + '%' : '0');
      $('#recorder .rec-play').toggleClass('is-playing', !a.paused).attr('aria-label', a.paused ? '녹음 다시 듣기' : '일시정지');
    }
    $(document).on('click', '#recorder .rec-play', function () {
      var a = $('#recorder .recorder__audio')[0]; if (!a || !st.url) return;
      if (a.paused) { var p = a.play(); if (p && p.catch) p.catch(function () { /* 무시 */ }); } else a.pause();
    });
    $(document).on('click', '#recorder .rec-player__bar', function (e) {
      var a = $('#recorder .recorder__audio')[0]; if (!a) return;
      var total = isFinite(a.duration) && a.duration > 0 ? a.duration : st.sec;
      var r = this.getBoundingClientRect();
      if (total && r.width) { try { a.currentTime = Math.max(0, Math.min(total, (e.clientX - r.left) / r.width * total)); } catch (err) { /* 무시 */ } }
    });

    $('#voice-btn').off('click').on('click', function () { if (st.state === 'rec' || st.state === 'paused') stop(); else start(); });
    $(document).on('click', '#recorder .rec-start', start);
    $(document).on('click', '#recorder .rec-pause', pauseToggle);
    $(document).on('click', '#recorder .rec-stop', stop);
    $(document).on('click', '#recorder .rec-reset', reset);
    $(document).on('click', '#recorder .rec-redo', redo);
    $(document).on('input', '#voice_text', function () { $(this).closest('.voice-box').toggleClass('is-empty', !$.trim(this.value)); if (st.state !== 'rec' && st.state !== 'paused') $('#recorder .rec-reset').prop('disabled', !st.url && !$.trim(this.value)); });
    $('#field-form').on('safet:validate', function (e) {
      if (st.state === 'rec' || st.state === 'paused') { e.preventDefault(); S.toast('녹음을 중지한 뒤 다음으로 가 주세요.'); }
    });
    $('#v-field').on('safet:hide', function () { stop(); });
    if ($('#voice-slot').length) ensureUI();
    var au = $('#recorder .recorder__audio');
    au.on('timeupdate play pause ended loadedmetadata', updatePlayer).on('ended', function () { this.currentTime = 0; updatePlayer(); });
    S.voiceRecorder = { state: function () { return st.state; }, seconds: function () { return st.sec; } };
  });
})(jQuery, window.SafeT);
