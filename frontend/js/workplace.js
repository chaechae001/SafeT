/* =========================================================
   사업장 관리 (workplace.html) · B01 목록 · B02 등록 · B02-E 수정
   업종별 기기 목록과 사업장은 합성 예시입니다(API 연결 전).
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  // machine_category (biz_code 별) · 합성 예시. 코드 확정 후 교체
  var MACHINES = {
    chicken: { name: '치킨', list: ['튀김기', '가스레인지', '식기세척기', '염지기', '업소용 냉장고', '칼·도마', '튀김 바스켓', '포장 실링기'] },
    snack: { name: '분식', list: ['가스레인지', '튀김기', '업소용 냉장고', '떡볶이 조리기', '칼·도마', '식기세척기'] },
    cafe: { name: '카페', list: ['에스프레소 머신', '제빙기', '블렌더', '온수기', '업소용 냉장고', '식기세척기'] },
    korean: { name: '한식', list: ['가스레인지', '업소용 냉장고', '칼·도마', '식기세척기', '대형 국솥', '밥솥'] },
    etc: { name: '기타', list: ['가스레인지', '업소용 냉장고', '칼·도마', '식기세척기'] }
  };

  // workplaces + workplace_machine · 합성 예시
  var WORKPLACES = {
    1: { name: '온기치킨 성수점', biz: 'chicken', machines: ['튀김기', '가스레인지', '업소용 냉장고', '칼·도마', '염지기'], custom: [] },
    2: { name: '온기분식', biz: 'snack', machines: ['가스레인지', '업소용 냉장고', '튀김기'], custom: [] }
  };

  function normalize(s) { return $.trim(s).replace(/\s+/g, ' '); }

  function machineRow(name, checked, custom) {
    var $l = $('<label class="check">');
    $('<input type="checkbox">').attr('name', custom ? 'machine_nm' : 'machine_code').val(name)
      .attr('data-name', name).prop('checked', checked).appendTo($l);
    var $t = $('<span class="check__text">').text(name).appendTo($l);
    if (custom) $t.append(' ', '<span class="src src--manual">직접 추가</span>');
    return $l;
  }

  /** 업종 목록을 불러옵니다. checked 에 있는 기기만 체크, custom 은 끝에 '직접 추가' */
  function renderMachines($view, biz, checked, custom) {
    var $grid = $view.find('.machine-grid').empty();
    $.each(MACHINES[biz].list, function (_, n) {
      $grid.append(machineRow(n, $.inArray(n, checked || []) > -1, false));
    });
    $.each(custom || [], function (_, n) { $grid.append(machineRow(n, true, true)); });
    $view.find('.js-biz-label').text('· ' + MACHINES[biz].name + ' 업종 목록');
  }

  /** 직접 추가: 앞뒤 공백 정리, 같은 이름은 합침 */
  function addMachine($view) {
    var $in = $view.find('.js-machine-input');
    var name = normalize($in.val());
    SafeT.clearError($in);
    if (!name) {
      SafeT.fieldError($in, '기기 이름을 입력해 주세요.');
      $in.trigger('focus');
      return;
    }
    var $same = $view.find('.machine-grid input').filter(function () {
      return normalize($(this).attr('data-name')) === name;
    });
    if ($same.length) {
      $same.prop('checked', true);
      SafeT.toast('이미 목록에 있는 기기라 체크했어요.');
    } else {
      $view.find('.machine-grid').append(machineRow(name, true, true));
      var el = $view.find('.machine-scroll').get(0);
      if (el) el.scrollTop = el.scrollHeight;
    }
    $in.val('').trigger('focus');
  }

  function checkedNames($view, custom) {
    return $view.find('.machine-grid input:checked')
      .filter(custom ? '[name="machine_nm"]' : '[name="machine_code"]')
      .map(function () { return $(this).attr('data-name'); }).get();
  }

  $(function () {
    var editing = null;

    /* ---------- B02 등록 ---------- */
    var $new = $('#v-new');
    renderMachines($new, $new.find('input[name="biz_code"]:checked').val() || 'chicken', [], []);

    // 업종을 바꾸면 그 업종 목록을 새로 불러오고 체크·직접 추가 기기를 모두 초기화
    $new.on('change', 'input[name="biz_code"]', function () {
      renderMachines($new, this.value, [], []);
    });

    // 회원가입 직후 첫 등록이면 취소 없음 (workplace.html?first=1#v-new)
    if (/[?&]first=1/.test(window.location.search)) $('#new-cancel').prop('hidden', true);

    $('.js-machine-add').on('click', function () {
      addMachine($(this).closest('.view'));
    });

    /* ---------- B02-E 수정 ---------- */
    $('#v-list').on('click', '[data-work]', function (e) {
      e.preventDefault();
      editing = $(this).data('work');
      SafeT.go('v-edit', { work: editing });
    });

    $('#v-edit').on('safet:show', function (e, o) {
      if (o && o.work) editing = o.work;
      if (!editing) editing = 1;
      var w = WORKPLACES[editing];
      $('#workplace-edit-workplace').val(w.name);
      $('#biz_nm').val(MACHINES[w.biz].name);              // 업종은 잠김
      $(this).find('input[name="work_no"]').val(editing);
      renderMachines($(this), w.biz, w.machines, w.custom);
    });

    $('#workplace-edit-wp-form').on('safet:submit', function (e) {
      e.preventDefault();
      var $v = $('#v-edit');
      var w = WORKPLACES[editing];
      SafeT.loading(true);                               // 사업장 저장: 원형 로딩만
      SafeT.wait(500).then(function () {
        w.name = normalize($('#workplace-edit-workplace').val());
        w.machines = checkedNames($v, false);
        w.custom = checkedNames($v, true);
        var $card = $('#v-list [data-work="' + editing + '"]').closest('[data-work-card]');
        $card.find('.card__title').contents().first().replaceWith(document.createTextNode(w.name + ' '));
        var $tags = $card.find('.tag-list').empty();
        $.each(w.machines.concat(w.custom), function (_, n) { $('<li class="tag">').text(n).appendTo($tags); });
        SafeT.loading(false);
        SafeT.toast('저장했어요');
        SafeT.go('v-list');
      });
    });

    /* ---------- B01 삭제 (사용 여부 N) ---------- */
    $('.modal[id^="delete-"]').on('click', '.btn--primary', function (e) {
      e.preventDefault();
      var id = $(this).closest('.modal').attr('id');
      $('#v-list a[href="#' + id + '"]').closest('[data-work-card]').remove();
      SafeT.toast('사업장을 목록에서 숨겼어요. 평가표 기록은 그대로 남아요.');
      SafeT.go('v-list');
    });
  });
})(jQuery, window.SafeT);
