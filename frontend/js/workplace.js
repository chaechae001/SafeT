/* =========================================================
   사업장 관리 (workplace.html) · B01 목록 · B02 등록 · B02-E 수정 · 화면설계서 08~09쪽
   백엔드 API 와 연결되어 있습니다 (backend/routers/workplaces.py, 로그인 필요).
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
    var $grid = $view.find('.machine-grid').empty();
    var $err = $view.find('.js-machine-error').prop('hidden', true);
    var name = '';
    $.each(bizList || [], function (_, b) { if (b.biz_code === biz) name = b.biz_nm; });
    $view.find('.js-biz-label').text(name ? '· ' + name + ' 업종 목록' : '');
    $view.data('biz', biz);

    function addCustom() {
      $.each(customNames || [], function (_, n) { $grid.append(machineRow(n, true, null)); });
    }

    return loadMachines(biz).done(function (list) {
      $.each(list, function (_, m) {
        $grid.append(machineRow(m.machine_nm, $.inArray(m.machine_code, checkedCodes || []) > -1, m.machine_code));
      });
      if (!list.length) $view.find('.js-machine-hint').text('이 업종에 등록된 기기가 없어요. 필요하면 직접 추가해 주세요.');
      addCustom();
    }).fail(function () {
      // 기기 목록을 못 불러와도 직접 추가로 계속 (09쪽)
      $err.prop('hidden', false);
      addCustom();
    });
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
    $in.val('').trigger('focus');
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
        var $li = $('<li class="card wp-card" data-work-card>').data('workplace', w);
        var $head = $('<div class="card__head">').appendTo($li);
        $('<p class="card__title">').text(w.workplace + ' ')
          .append($('<span class="muted small">').text('· ' + (w.biz_nm || w.biz_code))).appendTo($head);
        $('<button class="btn btn--sm" type="button" data-edit>수정</button>').attr('data-edit', w.work_no).appendTo($head);

        var $row = $('<div class="wp-card__row">').appendTo($li);
        var $d = $('<details class="wp-card__machines">').appendTo($row);
        $('<summary class="wp-card__toggle"><span class="when-closed">더보기</span><span class="when-open">접기</span></summary>').appendTo($d);
        var $tags = $('<ul class="tag-list">').appendTo($d);
        if (!w.machines.length) $('<li class="muted small">').text('등록한 기기가 없어요.').appendTo($tags);
        $.each(w.machines, function (_, m) { $('<li class="tag">').text(m.machine_nm).appendTo($tags); });
        $('<button class="btn btn--sm btn--danger wp-card__delete" type="button">삭제</button>').attr('data-delete', w.work_no).appendTo($row);
        $list.append($li);
      });
      $('#wp-empty').prop('hidden', rows.length > 0);
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
    $view.find('.js-biz-label').text('');
    $view.find('.js-machine-error').prop('hidden', true);
    $view.find('.js-machine-hint').text('업종을 고르면 기기 목록이 나와요. 매장에 있는 기기만 체크해 주세요.');
    $view.removeData('biz');

    var $opts = $('#new-biz').empty();
    loadBizList().done(function (list) {
      if (!list.length) {
        $('#new-biz-msg').removeClass('error-text').text('등록된 업종이 없어요. 관리자에게 문의해 주세요.').prop('hidden', false);
      }
      $.each(list, function (_, b) {
        var $l = $('<label>');
        $('<input type="radio" name="biz_code">').val(b.biz_code).appendTo($l);   // 필수 검사는 safet:validate 에서
        $l.append(document.createTextNode(' ' + (b.biz_nm || b.biz_code)));
        $opts.append($l);
      });
    }).fail(function (err) {
      $('#new-biz-msg').addClass('error-text').text(err.message || '업종 목록을 불러오지 못했어요.').prop('hidden', false);
    });
  }

  /* ---------- B02-E 수정 ---------- */
  function initEdit(no) {
    var $view = $('#v-edit');
    SafeT.clearErrors($view);
    $view.find('.machine-grid').empty();
    SafeT.loading(true);
    $.when(loadBizList(), api.get('/workplaces/' + no)).done(function (_, w) {
      editing = w.work_no;
      editingBiz = w.biz_code;
      $('#edit-workplace').val(w.workplace);
      $('#edit-biz').val(w.biz_nm || w.biz_code);                 // 업종은 잠김
      var codes = [], custom = [];
      $.each(w.machines, function (_, m) { if (m.custom) custom.push(m.machine_nm); else codes.push(m.machine_code); });
      renderMachines($view, w.biz_code, codes, custom);
    }).fail(function (err) {
      SafeT.toast(err.message || '사업장을 불러오지 못했어요.');
      SafeT.go('v-list');
    }).always(function () { SafeT.loading(false); });
  }

  $(function () {
    // 회원가입·로그인 직후 첫 등록이면 취소 없음 (workplace.html?first=1#v-new)
    if (/[?&]first=1/.test(window.location.search)) $('#new-cancel').prop('hidden', true);

    $('#v-list').on('safet:show', renderList);
    $('#wp-retry').on('click', renderList);

    // 수정
    $('#wp-list').on('click', '[data-edit]', function () {
      SafeT.go('v-edit', { work: +$(this).attr('data-edit') });
    });
    $('#v-edit').on('safet:show', function (e, o) {
      var no = (o && o.work) || editing;
      if (!no) { SafeT.go('v-list'); return; }
      initEdit(no);
    });

    // 삭제 = 사용 안 함 (08쪽: 확인 창, 작성 중 평가표 수 안내)
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

    // 업종을 바꾸면 그 업종 목록을 새로 불러오고, 체크와 직접 추가한 기기를 모두 초기화 (09쪽)
    $('#new-biz').on('change', 'input[name="biz_code"]', function () {
      $('#new-biz-msg').prop('hidden', true);
      $('#new-biz input').removeClass('is-invalid');
      renderMachines($('#v-new'), this.value, [], []);
    });

    $('.js-machine-add').on('click', function () { addMachine($(this).closest('.view')); });
    $('.js-machine-retry').on('click', function () {
      var $v = $(this).closest('.view');
      var keep = collect($v);
      renderMachines($v, $v.data('biz'), keep.machine_codes, keep.custom_machines);
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
      if ($btn.prop('disabled')) return;
      $btn.prop('disabled', true);
      SafeT.loading(true);                                       // 사업장 저장: 원형 로딩만
      api.post('/workplaces', $.extend({
        workplace: $('#new-workplace').val(),
        biz_code: $('#new-biz input:checked').val()
      }, collect($view))).done(function () {
        SafeT.toast('사업장을 등록했어요.');
        setTimeout(function () { window.location.href = 'home.html'; }, 600);   // 등록 저장 → H01
      }).fail(function (err) {
        showSaveError(err, $view);
        $btn.prop('disabled', false);
        SafeT.loading(false);
      });
    });

    $('#edit-form').on('safet:submit', function (e) {
      e.preventDefault();
      var $view = $('#v-edit');
      var $btn = $view.find('[type="submit"]');
      if ($btn.prop('disabled') || !editing) return;
      $btn.prop('disabled', true);
      SafeT.loading(true);
      api.put('/workplaces/' + editing, $.extend({ workplace: $('#edit-workplace').val() }, collect($view)))
        .done(function () {
          SafeT.toast('저장했어요.');
          SafeT.go('v-list');
        })
        .fail(function (err) { showSaveError(err, $view); })
        .always(function () { $btn.prop('disabled', false); SafeT.loading(false); });
    });

    // 처음 열린 화면 그리기 (common.js 의 화면 전환이 이 파일보다 먼저 실행됨)
    var $cur = SafeT.currentView();
    if ($cur.attr('id') === 'v-edit') SafeT.go('v-list');
    else $cur.trigger('safet:show', [{}]);
  });
})(jQuery, window.SafeT);
