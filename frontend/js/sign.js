/* =========================================================
   참여자 서명 (sign.html) · SIGN ① 참여자 선택 · ② 서명 · 화면설계서 29쪽
   API (로그인 필요, backend/routers/sign.py)
     GET  /evals/{번호}/signs   참여 근로자별 서명 여부 (서명 이미지는 받지 않음)
     POST /evals/{번호}/signs   {member_no, confirm: true, sign_img: PNG data URL}
   - 확인 체크 + 서명 획이 있어야 '서명 저장' 활성
   - 저장한 서명은 정정 불가, 저장은 원형 로딩만, 서버 성공 응답 후에만 '서명 완료'로 표시
   - 전원 서명 완료 시 '모두 서명했습니다' + 하단 '내 평가표로'
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var evalNo = Number(new URLSearchParams(location.search).get('eval')) || (SafeT.current && SafeT.current.evalNo());
  var data = null;                // 서버 응답 (summary)
  var hasStroke = false, saving = false;
  var canvas, ctx;

  function member(no) {
    return (data ? data.members : []).filter(function (m) { return m.member_no === no; })[0] || null;
  }
  function pickedNo() {
    var v = $('#signer-list input:checked').val();
    return v ? Number(v) : null;
  }

  /* ---------- ① 참여자 목록 ---------- */
  function render(res) {
    data = res;
    $('.js-eval-nm').text(res.eval_nm || '평가표');
    $('#sign-count').text(res.signed_count + '/' + res.member_count);
    var keep = pickedNo();
    var $list = $('#signer-list').removeAttr('aria-busy');
    $list.children('label').remove();
    $.each(res.members, function (_, m) {
      var $l = $('<label class="check signer">').toggleClass('signer--done', m.signed);
      $('<input type="radio" name="member_no">').val(m.member_no)
        .prop({ disabled: m.signed, checked: !m.signed && m.member_no === keep }).appendTo($l);
      $('<span class="check__text">').append($('<b>').text(m.member_nm))
        .append(' <span class="muted small">· 참여 근로자</span>').appendTo($l);
      $('<span class="tag">').toggleClass('tag--warn', !m.signed)
        .text(m.signed ? '서명 완료' : '서명 필요').appendTo($l);
      $list.append($l);
    });
    $('#signer-empty').prop('hidden', res.member_count > 0);
    // UX-016: 모두 서명을 마치기 전에는 서명할 사람을 추가할 수 있음(참여자 0명이면 서명할 수 없던 문제)
    $('#signer-add').prop('hidden', !!res.sign_end_dt);
    var hasWriter = writer && res.members.some(function (x) { return x.member_nm === writer; });
    $('#signer-add-me').prop('hidden', !writer || hasWriter).text('+ 작성자 ' + (writer || '') + ' 추가');
    updatePick();
  }

  /* ---------- UX-016: 서명할 사람 추가 ---------- */
  var writer = null;
  function addSigner(name) {
    name = $.trim(name || '');
    if (!name) { SafeT.toast('이름을 입력해 주세요.'); $('#signer-add-name').trigger('focus'); return; }
    SafeT.loading(true);
    SafeT.api.post('/evals/' + evalNo + '/signs/members', { member_nm: name }).done(function (res) {
      $('#signer-add-name').val('');
      render(res);
      var added = res.members.filter(function (x) { return x.member_nm === name; })[0];
      if (added) { $('#signer-list input[value="' + added.member_no + '"]').prop('checked', true); updatePick(); }
      SafeT.toast(name + ' 님을 추가했어요. 이어서 서명해 주세요.');
    }).fail(function (err) { SafeT.toast(err.message); }).always(function () { SafeT.loading(false); });
  }

  function updatePick() {
    var allDone = !!data && data.member_count > 0 && data.signed_count === data.member_count;
    $('#sign-done').prop('hidden', !allDone);
    $('#to-home').prop('hidden', !(allDone || (data && !data.member_count)));
    $('#pick-btn').prop('hidden', allDone || (data && !data.member_count));
    var m = member(pickedNo());
    $('#pick-btn').prop('disabled', !m).text(m ? m.member_nm + '로 서명하기' : '본인 이름을 선택해 주세요');
  }

  function load() {
    return SafeT.api.get('/evals/' + evalNo + '/signs').done(render).fail(function (err) {
      SafeT.toast(err.message);
      if (err.code === 'EVAL_NOT_CONFIRMED' || err.status === 404) {
        setTimeout(function () { window.location.href = 'home.html'; }, 1200);
      }
    });
  }

  /* ---------- ② 서명 칸 ---------- */
  function updateSave() {
    $('#sign-save').prop('disabled', saving || !(hasStroke && $('#sign-form input[name="confirm_yn"]').is(':checked')));
  }

  function clearPad() {
    var r = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, r.width, r.height);
    hasStroke = false;
    updateSave();
  }

  /** 저장용 PNG: 화면 배율(devicePixelRatio)과 무관하게 칸 크기 그대로 줄여 흰 배경으로 (용량 제한 대비) */
  function exportPng() {
    var r = canvas.getBoundingClientRect();
    var out = document.createElement('canvas');
    out.width = Math.max(1, Math.round(r.width));
    out.height = Math.max(1, Math.round(r.height));
    var o = out.getContext('2d');
    o.fillStyle = '#ffffff';
    o.fillRect(0, 0, out.width, out.height);
    o.drawImage(canvas, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }

  function setupPad() {
    canvas = $('<canvas class="sign-pad" id="sign-canvas" role="img" aria-label="서명 입력 칸. 손가락이나 마우스로 직접 서명"></canvas>').get(0);
    $('#sign-pad').replaceWith(canvas);
    ctx = canvas.getContext('2d');
    var drawing = false;

    function resize() {
      var r = canvas.getBoundingClientRect();
      if (!r.width) return;
      var ratio = window.devicePixelRatio || 1;
      canvas.width = r.width * ratio;
      canvas.height = r.height * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = '#1d2420';
      hasStroke = false;              // 크기가 바뀌면 칸이 비워지므로 다시 서명
      updateSave();
    }
    function pos(e) {
      var r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    canvas.addEventListener('pointerdown', function (e) {
      if (saving) return;
      drawing = true;
      canvas.setPointerCapture(e.pointerId);
      var p = pos(e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!drawing) return;
      var p = pos(e);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      if (!hasStroke) { hasStroke = true; updateSave(); }
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (t) {
      canvas.addEventListener(t, function () { drawing = false; });
    });

    $('#v-draw').on('safet:show', resize);
    $(window).on('resize', resize);
    resize();
  }

  $(function () {
    setupPad();
    updateSave();
    if (!evalNo) {
      SafeT.toast('내 평가표에서 평가표를 다시 골라 주세요.');
      setTimeout(function () { window.location.href = 'home.html'; }, 1200);
      return;
    }
    if (SafeT.current) SafeT.current.setEval(evalNo);
    // UX-016: 작성자 이름(빠른 추가 버튼용)을 먼저 읽고 목록 표시
    SafeT.api.get('/evals/' + evalNo).done(function (d) { writer = d.eval_writer || null; }).always(load);
    $('#signer-add-form').on('submit', function (e) { e.preventDefault(); addSigner($('#signer-add-name').val()); });
    $('#signer-add-me').on('click', function () { addSigner(writer); });

    $('#signer-list').on('change', 'input', updatePick);

    // ① → ②: 고른 사람 이름으로 서명 화면
    $('#pick-form').on('safet:submit', function (e) {
      e.preventDefault();
      var m = member(pickedNo());
      if (!m || m.signed) { updatePick(); return; }
      $('#draw-name').text(m.member_nm + ' · 참여 근로자');
      $('#sign-form input[name="confirm_yn"]').prop('checked', false);
      SafeT.go('v-draw');
      clearPad();
    });

    // ② 화면을 주소로 바로 열었거나 고른 사람이 없으면 ①로
    $('#v-draw').on('safet:show', function () {
      if (!member(pickedNo())) SafeT.go('v-pick');
    });

    $('#sign-form').on('change', 'input[name="confirm_yn"]', updateSave);
    $('#sign-clear').on('click', clearPad);      // 서명 칸만 비우기

    $('#sign-form').on('safet:validate', function (e) {
      if (!hasStroke) {
        e.preventDefault();
        SafeT.toast('서명 칸에 직접 서명해 주세요.');
      }
    });

    $('#sign-form').on('safet:submit', function (e) {
      e.preventDefault();
      var m = member(pickedNo());
      if (saving || !m || !hasStroke || !$('#sign-form input[name="confirm_yn"]').is(':checked')) return;
      saving = true;
      updateSave();
      SafeT.loading(true);
      SafeT.api.post('/evals/' + evalNo + '/signs', { member_no: m.member_no, confirm: true, sign_img: exportPng() })
        .done(function (res) {
          render(res);                             // 서버가 돌려준 목록으로만 '서명 완료' 표시
          clearPad();
          SafeT.toast(m.member_nm + ' 님의 서명을 저장했어요');
          SafeT.go('v-pick');
        })
        .fail(function (err) {
          SafeT.toast(err.message);
          if (err.code === 'ALREADY_SIGNED' || err.code === 'MEMBER_NOT_FOUND') {
            load().always(function () { SafeT.go('v-pick'); });
          }
        })
        .always(function () {
          saving = false;
          SafeT.loading(false);
          updateSave();
        });
    });
  });
})(jQuery, window.SafeT);
