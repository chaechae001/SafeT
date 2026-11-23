/* =========================================================
   사업장 관리 (workplace.html) · B01 목록 · B02 등록 · B02-E 수정
   백엔드 API 와 연결되어 있습니다 (로그인 필요).
     GET    /biz-categories, /biz-categories/{업종}/machines
     GET    /workplaces, /workplaces/{번호}
     POST   /workplaces           등록 → 내 평가표(home.html)
     PUT    /workplaces/{번호}    수정 (사업장명·보유 기기, 업종 변경 불가) → 목록
     DELETE /workplaces/{번호}    삭제 = 사용 안 함 (평가표·기기 기록은 남음)
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  var api = SafeT.api;
  var bizList = null;          // [{ biz_code, biz_nm }]
  var catalog = {};            // 업종 코드 → [{ machine_code, machine_nm }]
  var editing = null;          // 수정 중인 사업장 번호
  var editingBiz = null;
  var editOriginal = null;     // 수정 화면에서 처음 받은 보유 기기 { codes: [], custom: [] } (다시 불러오기에 사용)
  var renderSeq = 0;           // 늦게 온 이전 기기 목록 응답이 화면을 덮지 않게

  /**
   * 기기 목록 상태 → 저장 버튼
   * - loading: 불러오는 중 → 저장 막음 (등록·수정 모두)
   * - failed : 수정 화면은 저장 막음 (빈 목록으로 저장하면 기존 기기가 지워짐)
   *            등록 화면은 직접 추가로 계속 가능
   * - ready  : 저장 가능
   */
  function setMachineState($view, st) {
    $view.data('machine-state', st);
    $view.find('.js-machine-loading').prop('hidden', st !== 'loading');
    $view.find('.js-machine-error').prop('hidden', st !== 'failed');
    syncSave($view);
    // 기존 정보가 늦게 도착해 사용자가 입력한 수정 내용을 덮어쓰지 않게 합니다.
    if ($view.attr('id') === 'v-edit') {
      $view.find('#edit-workplace, .js-machine-input, .js-machine-add').prop('disabled', st === 'loading');
    }
  }

  /** 저장 버튼은 기기 목록 상태 + 필수 칸(사업장명, 등록 화면은 업종까지)을 채웠을 때만 켬 */
  function syncSave($view) {
    var st = $view.data('machine-state');
    var isEdit = $view.attr('id') === 'v-edit';
    var block = st === 'loading' || (st === 'failed' && isEdit);
    var filled = !!normalize($view.find('input[name="workplace"]').val()) &&
      (isEdit || $view.find('input[name="biz_code"]:checked').length > 0);
    $view.find('.bottom-bar [type="submit"]').prop('disabled', block || !filled)
      .attr('title', !filled ? (isEdit ? '사업장명을 입력하면 저장할 수 있어요.' : '사업장명과 업종을 고르면 저장할 수 있어요.') : null);
  }

  function canSave($view) {
    var st = $view.data('machine-state');
    if (st === 'loading') return '기기 목록을 불러오는 중이에요. 잠시 뒤 저장해 주세요.';
    if (st === 'failed' && $view.attr('id') === 'v-edit') return '기기 목록을 불러오지 못했어요. 다시 불러온 뒤 저장해 주세요.';
    return null;
  }

  function normalize(s) { return $.trim(s || '').replace(/\s+/g, ' '); }
  function key(s) { return normalize(s).toLowerCase(); }

  /* ---------- 기기 목록 (등록·수정 공통) ---------- */
  function machineRow(name, checked, code) {
    var $l = $('<label class="check">');
    var $in = $('<input type="checkbox">').attr('data-name', name).prop('checked', checked).appendTo($l);
    if (code) $in.attr({ name: 'machine_codes', value: code, 'data-code': code });
    else $in.attr({ name: 'custom_machines', value: name, 'data-custom': '1' });
    var $t = $('<span class="check__text">').text(name).appendTo($l);
    if (!code) $t.append(' ', '<span class="src src--manual">직접 추가</span>');
    return $l;
  }

  function loadMachines(biz) {
    if (catalog[biz]) return $.Deferred().resolve(catalog[biz]).promise();
    return api.get('/biz-categories/' + encodeURIComponent(biz) + '/machines').done(function (list) {
      catalog[biz] = list;
    });
  }

  /** 업종 기기를 불러와 그립니다. checkedCodes 는 체크, customNames 는 끝에 '직접 추가' */
  function renderMachines($view, biz, checkedCodes, customNames) {
    var seq = ++renderSeq;
    var $grid = $view.find('.machine-grid').empty();
    var name = '';
    $.each(bizList || [], function (_, b) { if (b.biz_code === biz) name = b.biz_nm; });
    $view.find('.js-biz-label').text(name ? '· ' + name + ' 업종 목록' : '');
    $view.data('biz', biz);
    setMachineState($view, 'loading');

    function addCustom() {
      $.each(customNames || [], function (_, n) { $grid.append(machineRow(n, true, null)); });
    }

    var d = $.Deferred();
    loadMachines(biz).done(function (list) {
      if (seq !== renderSeq) return;
      $.each(list, function (_, m) {
        $grid.append(machineRow(m.machine_nm, $.inArray(m.machine_code, checkedCodes || []) > -1, m.machine_code));
      });
      if (!list.length) $view.find('.js-machine-hint').text('이 업종에 등록된 기기가 없어요. 필요하면 직접 추가해 주세요.');
      // 목록이 나오면 '업종을 고르면…' 안내는 숨기고, 매장에 있는 기기만 고르라는 안내로
      else $view.find('.js-machine-hint').text('매장에 있는 기기만 골라 주세요. 없는 기기는 아래에서 직접 추가할 수 있어요.');
      addCustom();
      setMachineState($view, 'ready');
      updateCount($view);
      d.resolve();
    }).fail(function () {
      if (seq !== renderSeq) return;
      // 등록: 직접 추가로 계속 / 수정: 다시 불러올 때까지 저장 막음
      addCustom();
      setMachineState($view, 'failed');
      updateCount($view);
      d.reject();
    });
    return d.promise();
  }

  /** 직접 추가: 앞뒤 공백 정리, 같은 이름(목록 기기 포함)은 합침 */
  function addMachine($view) {
    var $in = $view.find('.js-machine-input');
    var name = normalize($in.val());
    SafeT.clearError($in);
    if (!name) {
      SafeT.fieldError($in, '기기 이름을 입력해 주세요.');
      $in.trigger('focus');
      return;
    }
    if (name.length > 50) {
      SafeT.fieldError($in, '기기 이름은 50자 이내로 입력해 주세요.');
      $in.trigger('focus');
      return;
    }
    var $same = $view.find('.machine-grid input').filter(function () {
      return key($(this).attr('data-name')) === key(name);
    });
    if ($same.length) {
      $same.prop('checked', true);
      SafeT.toast('이미 목록에 있는 기기라 체크했어요.');
    } else {
      $view.find('.machine-grid').append(machineRow(name, true, null));
      var el = $view.find('.machine-scroll').get(0);
      if (el) el.scrollTop = el.scrollHeight;
    }
    updateCount($view);
    $in.val('').trigger('focus');
  }

  /** 선택한 기기 수 표시 (바뀔 때 살짝 강조) */
  function updateCount($view) {
    var n = $view.find('.machine-grid input:checked').length;
    var total = $view.find('.machine-grid input').length;
    var $c = $view.find('.js-machine-count');
    if (!total) { $c.prop('hidden', true); return; }
    var text = '선택한 기기 ' + n + '개 / 전체 ' + total + '개';
    if ($c.text() !== text) {
      $c.text(text).prop('hidden', false).removeClass('is-bump');
      void $c[0].offsetWidth;                       // 애니메이션 다시 시작
      $c.addClass('is-bump');
    }
  }

  function collect($view) {
    return {
      machine_codes: $view.find('.machine-grid input[data-code]:checked').map(function () { return $(this).attr('data-code'); }).get(),
      custom_machines: $view.find('.machine-grid input[data-custom]:checked').map(function () { return $(this).attr('data-name'); }).get()
    };
  }

  /** API 오류를 입력칸 아래 또는 알림으로 */
  function showSaveError(err, $view) {
    var map = { workplace: $view.find('input[name="workplace"]'), custom_machines: $view.find('.js-machine-input') };
    var $f = err.code === 'INVALID' ? map[err.field] : null;
    if ($f && $f.length) {
      SafeT.fieldError($f, err.message);
      $f.trigger('focus');
    } else {
      SafeT.toast(err.message);
    }
  }

  function loadBizList() {
    if (bizList) return $.Deferred().resolve(bizList).promise();
    return api.get('/biz-categories').done(function (list) { bizList = list; });
  }

  /* ---------- B01 목록 ---------- */
  function renderList() {
    var $list = $('#wp-list');
    $('#wp-error').prop('hidden', true);
    return api.get('/workplaces').done(function (rows) {
      $list.empty();
      $.each(rows, function (_, w) {
        // 카드: 이름 + [업종 | 값] 배지 / 오른쪽 수정·⋮ / 회색 기기 상자(통째로 눌러 펼치기) / 구분선 아래 사업장 삭제
        var $li = $('<li class="card wp-card" data-work-card>').data('workplace', w);
        var $head = $('<div class="card__head">').appendTo($li);
        var $t = $('<div class="wp-card__title">').appendTo($head);
        $('<p class="card__title">').text(w.workplace).appendTo($t);
        var $acts = $('<div class="wp-card__acts">').appendTo($head);
        $('<button class="btn btn--sm wp-card__edit" type="button">수정</button>').attr('data-edit', w.work_no)
          .attr('aria-label', w.workplace + ' 수정').appendTo($acts);

        // 업종 배지는 머리 줄 아래 전체 폭에 (좁은 화면에서 업종 이름이 잘게 줄바꿈되지 않게)
        $('<p class="wp-biz">').append(
          $('<span class="wp-biz__label">').text('업종'),
          $('<span class="wp-biz__value">').text(w.biz_nm || w.biz_code)
        ).appendTo($li);

        var n = w.machines.length;
        var boxId = 'wp-machines-' + w.work_no;
        var $box = $('<div class="wp-acc">').appendTo($li);
        $('<button class="wp-acc__toggle" type="button" aria-expanded="false">').attr('aria-controls', boxId).append(
          $('<span class="wp-acc__icon">').html(SafeT.icon('machine')),
          $('<span class="wp-acc__title">').text('보유 기기 ' + n + '개'),
          $('<span class="wp-acc__state">').append(
            $('<span class="when-closed">').text('보기'), $('<span class="when-open">').text('접기'),
            SafeT.icon('chevronDown', 'wp-acc__chev'))
        ).appendTo($box);
        var $body = $('<div class="wp-acc__body" hidden>').attr('id', boxId).appendTo($box);
        var $ul = $('<ul class="wp-acc__list">').appendTo($body);
        if (!n) $('<li class="wp-acc__empty">').text('등록한 기기가 없어요.').appendTo($ul);
        $.each(w.machines, function (_, m) {
          var $m = $('<li>').text(m.machine_nm).appendTo($ul);
          if (m.custom) $m.append(' ', $('<span class="wp-acc__src">').text('(직접 추가)'));   // 기기 상태 정보는 없어서 표시하지 않음
        });
        $('<button class="wp-acc__add" type="button">').attr('data-add-machine', w.work_no)
          .html(SafeT.icon('plus')).append('기기 추가').appendTo($body);

        var $foot = $('<div class="wp-card__foot">').appendTo($li);
        $('<button class="btn btn--sm btn--ghost wp-card__delete" type="button">').html(SafeT.icon('trash')).append('사업장 삭제')
          .attr('data-delete', w.work_no).attr('aria-label', w.workplace + ' 삭제').appendTo($foot);
        $list.append($li);
      });
      $('#wp-empty').prop('hidden', rows.length > 0);
      $('#wp-summary').text('등록된 사업장 ' + rows.length + '개').prop('hidden', !rows.length);
    }).fail(function (err) {
      $('#wp-error').prop('hidden', false).find('.js-msg').text(err.message || '사업장 목록을 불러오지 못했어요.');
    });
  }

  /* ---------- B02 등록 ---------- */
  function initNew() {
    var $view = $('#v-new');
    $('#new-form').get(0).reset();
    SafeT.clearErrors($view);
    $('#new-biz-msg').prop('hidden', true);
    $view.find('.machine-grid').empty();
    updateCount($view);
    $view.find('.js-biz-label').text('');
    $view.find('.js-machine-hint').text('업종을 고르면 기기 목록이 나와요. 매장에 있는 기기만 체크해 주세요.');
    $view.removeData('biz').addClass('wp-no-biz');            // 업종 고르기 전 = 안내 상자만
    setMachineState($view, 'idle');          // 업종을 고르기 전 (저장하면 업종 필수 안내)

    var $opts = $('#new-biz').empty();
    loadBizList().done(function (list) {
      if (!list.length) {
        $('#new-biz-msg').removeClass('error-text').text('등록된 업종이 없어요. 관리자에게 문의해 주세요.').prop('hidden', false);
      }
      $.each(list, function (_, b) {
        var $l = $('<label>');
        $('<input type="radio" name="biz_code">').val(b.biz_code).appendTo($l);   // 필수 검사는 safet:validate 에서
        $l.append(document.createTextNode(' ' + (b.biz_nm || b.biz_code)), SafeT.icon('check', 'wp-chip-check'));
        $opts.append($l);
      });
    }).fail(function (err) {
      $('#new-biz-msg').addClass('error-text').text(err.message || '업종 목록을 불러오지 못했어요.').prop('hidden', false);
    });
  }

  /* ---------- B02-E 수정 ---------- */
  function initEdit(no, focusAdd) {
    var $view = $('#v-edit');
    SafeT.clearErrors($view);
    $view.find('.machine-grid').empty();
    editOriginal = null;
    setMachineState($view, 'loading');        // 사업장·기기 정보를 받기 전에는 저장 막음
    SafeT.loading(true);
    $.when(loadBizList(), api.get('/workplaces/' + no)).done(function (_, w) {
      editing = w.work_no;
      editingBiz = w.biz_code;
      $('#edit-workplace').val(w.workplace);
      $('#edit-biz').val(w.biz_nm || w.biz_code);                 // 업종은 잠김
      var codes = [], custom = [];
      $.each(w.machines, function (_, m) { if (m.custom) custom.push(m.machine_nm); else codes.push(m.machine_code); });
      editOriginal = { codes: codes, custom: custom };            // 다시 불러오기 때 원래 체크 복구용
      renderMachines($view, w.biz_code, codes, custom).always(function () {
        // 목록 카드의 '기기 추가'로 들어오면 직접 추가 칸으로 바로 이동
        if (focusAdd) {
          var el = document.getElementById('edit-machine-add');
          if (el && !el.disabled) { el.scrollIntoView({ block: 'center' }); el.focus({ preventScroll: true }); }
        }
      });
    }).fail(function (err) {
      SafeT.toast(err.message || '사업장을 불러오지 못했어요.');
      SafeT.go('v-list');
    }).always(function () { SafeT.loading(false); });
  }

  $(function () {
    var fromEquipment=new URLSearchParams(location.search).get('from')==='equipment';
    $('#wp-resume-write').prop('hidden',!fromEquipment);
    // 회원가입·로그인 직후 첫 등록이면 취소 없음 (workplace.html?first=1#v-new)
    if (/[?&]first=1/.test(window.location.search)) {
      $('#new-cancel').prop('hidden', true);
      $('#wp-first').prop('hidden', false);          // 첫 등록 이유·다음 단계 안내
    }
    // 기기 체크가 바뀌면 선택 수 갱신
    $('.machine-grid').on('change', 'input', function () { updateCount($(this).closest('.view')); });

    $('#v-list').on('safet:show', renderList);
    $('#wp-retry').on('click', renderList);

    // 수정
    $('#wp-list').on('click', '[data-edit]', function () {
      SafeT.go('v-edit', { work: +$(this).attr('data-edit') });
    });
    $('#v-edit').on('safet:show', function (e, o) {
      var no = (o && o.work) || editing;
      if (!no) { SafeT.go('v-list'); return; }
      initEdit(no, !!(o && o.focusAdd));
    });

    // 삭제 = 사용 안 함 (확인 창, 작성 중 평가표 수 안내)
    $('#wp-list').on('click', '[data-delete]', function () {
      var w = $(this).closest('[data-work-card]').data('workplace');
      var msg = '‘' + w.workplace + '’을(를) 목록과 새 평가표의 사업장 선택에서 숨겨요. 이 사업장의 평가표와 기기 기록은 그대로 남아요.';
      if (w.draft_count) msg += ' 작성 중인 평가표 ' + w.draft_count + '건이 이 사업장에 연결되어 있어요.';
      SafeT.confirm({ title: '사업장을 삭제할까요?', message: msg, ok: '삭제', cancel: '취소', danger: true }).then(function (yes) {
        if (yes !== true) return;
        SafeT.loading(true);
        api.del('/workplaces/' + w.work_no).done(function () {
          SafeT.toast('사업장을 삭제했어요. 평가표 기록은 그대로 남아요.');
          renderList();
        }).fail(function (err) {
          SafeT.toast(err.message);
        }).always(function () { SafeT.loading(false); });
      });
    });

    // 등록
    $('#v-new').on('safet:show', initNew);

    // 업종을 바꾸면 그 업종 목록을 새로 불러오고, 체크와 직접 추가한 기기를 모두 초기화
    $('#new-biz').on('change', 'input[name="biz_code"]', function () {
      $('#new-biz-msg').prop('hidden', true);
      $('#new-biz input').removeClass('is-invalid');
      $('#v-new').removeClass('wp-no-biz');
      renderMachines($('#v-new'), this.value, [], []);
    });

    $('.js-machine-add').on('click', function () { addMachine($(this).closest('.view')); });
    $('.js-machine-retry').on('click', function () {
      var $v = $(this).closest('.view');
      var keep = collect($v);
      // 수정 화면: 실패한 동안 화면에서 빠진 업종 기기는 처음 받은 정보로 되살림 (직접 추가는 지금 화면 그대로)
      var codes = ($v.attr('id') === 'v-edit' && editOriginal) ? editOriginal.codes : keep.machine_codes;
      renderMachines($v, $v.data('biz'), codes, keep.custom_machines);
    });

    $('#new-form').on('safet:validate', function (e) {
      if (!$('#new-biz input:checked').length) {
        e.preventDefault();
        $('#new-biz input').first().addClass('is-invalid');
        $('#new-biz-msg').addClass('error-text').text('업종을 선택해 주세요.').prop('hidden', false);
      }
    });

    $('#new-form').on('safet:submit', function (e) {
      e.preventDefault();
      var $view = $('#v-new');
      var $btn = $view.find('[type="submit"]');
      var blocked = canSave($view);
      if (blocked) { SafeT.toast(blocked); return; }      // 엔터 키 등으로 버튼을 거치지 않은 경우까지
      if ($btn.prop('disabled')) return;
      $btn.prop('disabled', true);
      SafeT.loading(true);                                       // 사업장 저장: 원형 로딩만
      api.post('/workplaces', $.extend({
        workplace: $('#new-workplace').val(),
        biz_code: $('#new-biz input:checked').val()
      }, collect($view))).done(function () {
        SafeT.toast('사업장을 등록했어요.');
        setTimeout(function () { if(fromEquipment){SafeT.go('v-list');}else{window.location.href = 'home.html';} }, 600);   // 등록 저장 → H01
      }).fail(function (err) {
        showSaveError(err, $view);
        syncSave($view);
        SafeT.loading(false);
      });
    });

    $('#edit-form').on('safet:submit', function (e) {
      e.preventDefault();
      var $view = $('#v-edit');
      var $btn = $view.find('[type="submit"]');
      // 기기 목록을 불러오는 중·실패 상태면 저장하지 않음 (빈 목록으로 기존 기기가 지워지는 것 방지)
      var blocked = canSave($view) || (!editOriginal ? '사업장 정보를 불러온 뒤 저장해 주세요.' : null);
      if (blocked) { SafeT.toast(blocked); return; }
      if ($btn.prop('disabled') || !editing) return;
      $btn.prop('disabled', true);
      SafeT.loading(true);
      api.put('/workplaces/' + editing, $.extend({ workplace: $('#edit-workplace').val() }, collect($view)))
        .done(function () {
          SafeT.toast('저장했어요.');
          SafeT.go('v-list');
        })
        .fail(function (err) { showSaveError(err, $view); })
        .always(function () { setMachineState($view, $view.data('machine-state')); SafeT.loading(false); });
    });

    var first = /[?&]first=1/.test(window.location.search);
    // 등록·수정 화면: ☰ 대신 ← (목록으로) + 가운데 Safe-T. 첫 등록(취소 없음)은 기존처럼 ☰ 유지
    $('#v-new, #v-edit').on('safet:show', function () {
      var sub = !(first && this.id === 'v-new');
      $('body').toggleClass('wp-sub', sub);
      $('#wp-back').prop('hidden', !sub);
    }).on('safet:hide', function () {
      $('body').removeClass('wp-sub');
      $('#wp-back').prop('hidden', true);
    });
    // 저장 버튼: 사업장명 입력·업종 선택에 맞춰 켜고 끔
    $('#v-new, #v-edit').on('input change', 'input[name="workplace"], input[name="biz_code"]', function () {
      syncSave($(this).closest('.view'));
    });

    // 보유 기기 상자: 통째로 눌러 펼치기·접기
    $('#wp-list').on('click', '.wp-acc__toggle', function () {
      var open = $(this).attr('aria-expanded') !== 'true';
      $(this).attr('aria-expanded', String(open)).closest('.wp-acc').toggleClass('is-open', open)
        .find('.wp-acc__body').prop('hidden', !open);
    });
    // 기기 추가 → 수정 화면의 직접 추가 칸
    $('#wp-list').on('click', '[data-add-machine]', function () {
      SafeT.go('v-edit', { work: +$(this).attr('data-add-machine'), focusAdd: true });
    });


    // 처음 열린 화면 그리기 (common.js 의 화면 전환이 이 파일보다 먼저 실행됨)
    var $cur = SafeT.currentView();
    if ($cur.attr('id') === 'v-edit') SafeT.go('v-list');
    else $cur.trigger('safet:show', [{}]);
  });
})(jQuery, window.SafeT);
