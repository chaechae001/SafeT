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
      SafeT.api.post('/trash/' + t.eval_no + '/restore').done(function (r) {
        // 내 평가표에서 복원한 평가표가 바로 보이게: '작성 중' 탭, 사업장 -전체-, 기간에 평가일 포함
        // (사업장·기간 선택이 남아 있으면 다른 사업장·날짜의 평가표가 목록에서 가려짐)
        try {
          var s = JSON.parse(window.sessionStorage.getItem('safet.home') || '{}');
          var d = day(r && r.eval_dt);
          s.tab = 'W'; s.page = 1; s.scroll = 0; s.work = '';
          // 저장된 기간이 없으면 내 평가표 처음 값(이번 달 1일 ~ 오늘)에서 시작
          var today = SafeT.today();
          if (!s.from) s.from = SafeT.formatDate(new Date(today.getFullYear(), today.getMonth(), 1));
          if (!s.to) s.to = SafeT.formatDate(today);
          if (d !== '—') {
            if (s.from > d) s.from = d;                // 'YYYY.MM.DD' 문자열 비교
            if (s.to < d) s.to = d;
          }
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
