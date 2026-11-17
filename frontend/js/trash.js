/* =========================================================
   휴지통 (trash.html) · H02 · 화면설계서 31쪽
   API (로그인 필요, backend/routers/trash.py)
     GET    /trash                   목록 (30일 지난 것은 서버가 이때 영구 삭제)
     POST   /trash/{번호}/restore    복원 → 내 평가표 '작성 중' 탭
     DELETE /trash/{번호}            영구 삭제 (복원 불가)
   - 작성 중 초안만 30일 보관. 영구 삭제는 확인 창 후 실행
   - 서버 성공 응답 후에만 목록에서 뺌
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var busy = false;
  var target = null;              // 영구 삭제할 평가표 {eval_no, eval_nm}

  function day(iso) { return iso ? String(iso).slice(0, 10).replace(/-/g, '.') : '—'; }

  function render(res) {
    var $list = $('#trash-list').empty().removeAttr('aria-busy');
    $.each(res.items, function (_, e) {
      var $li = $('<li class="card">').attr('data-eval', e.eval_no);
      $('<p class="card__title">').text(e.eval_nm || '(이름 없는 평가표)').appendTo($li);
      $('<p class="card__meta">')
        .text([e.workplace || '', '작성 중', '삭제 ' + day(e.del_dt)].filter(Boolean).join(' · ') + ' · ')
        .append($('<strong>').text(e.days_left + '일 후 영구 삭제'))
        .appendTo($li);
      var $row = $('<div class="btn-row">').appendTo($li);
      $('<button class="btn" type="button" data-restore>').text('복원')
        .attr('aria-label', (e.eval_nm || '평가표') + ' 복원').appendTo($row);
      $('<button class="btn btn--danger" type="button" data-purge>').text('영구 삭제')
        .attr('aria-label', (e.eval_nm || '평가표') + ' 영구 삭제').appendTo($row);
      $list.append($li);
    });
    $('#trash-empty').prop('hidden', res.items.length > 0);
  }

  function load() {
    return SafeT.api.get('/trash').done(render).fail(function (err) {
      $('#trash-list').removeAttr('aria-busy');
      SafeT.toast(err.message);
    });
  }

  function card(btn) {
    var $li = $(btn).closest('[data-eval]');
    return { eval_no: Number($li.attr('data-eval')), eval_nm: $.trim($li.find('.card__title').text()) };
  }

  $(function () {
    load().done(function () {
      if (new URLSearchParams(location.search).get('deleted')) SafeT.toast('평가표를 휴지통으로 옮겼어요. 30일 안에 복원할 수 있어요.');
    });

    // 복원: 이전 입력 그대로 작성 중 탭으로 (내 평가표 탭을 '작성 중'으로 맞춤)
    $('#trash-list').on('click', '[data-restore]', function () {
      if (busy) return;
      var t = card(this);
      busy = true;
      SafeT.loading(true);
      SafeT.api.post('/trash/' + t.eval_no + '/restore').done(function () {
        try {
          var s = JSON.parse(window.sessionStorage.getItem('safet.home') || '{}');
          s.tab = 'W'; s.page = 1; s.scroll = 0;
          window.sessionStorage.setItem('safet.home', JSON.stringify(s));
        } catch (err) { /* 저장 불가 환경 */ }
        window.location.href = 'home.html';
      }).fail(function (err) {
        SafeT.toast(err.message);
        load();                                  // 보관 기간 지남 등: 목록 새로 고침
      }).always(function () { busy = false; SafeT.loading(false); });
    });

    // 영구 삭제: 확인 창 → 삭제
    $('#trash-list').on('click', '[data-purge]', function () {
      if (busy) return;
      target = card(this);
      $('#purge-1-title').text('‘' + target.eval_nm + '’을 영구 삭제할까요?');
      SafeT.openModal('purge-1');
    });

    $('#purge-ok').on('click', function () {
      if (busy || !target) return;
      var t = target;
      busy = true;
      SafeT.closeModal(true);
      SafeT.loading(true);
      SafeT.api.del('/trash/' + t.eval_no).done(function () {
        target = null;
        SafeT.toast('영구 삭제했어요.');
        load();
      }).fail(function (err) {
        SafeT.toast(err.message);
        load();
      }).always(function () { busy = false; SafeT.loading(false); });
    });
  });
})(jQuery, window.SafeT);
