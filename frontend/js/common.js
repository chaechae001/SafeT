/* =========================================================
   Safe-T 공통 동작 (common.js) · jQuery 3.7.1
   - 화면(view) 전환: 주소의 #view-id 를 기준으로 .is-active 를 옮김 (뒤로 가기 지원)
   - 확인 창(.modal): .is-open / Esc·바깥 클릭으로 닫기
   - 입력 검사: 오류는 입력칸 아래에 표시하고 첫 오류 칸으로 포커스
   - 날짜 입력칸 1개 + 달력 1개, 알림(토스트), 원형 로딩, 진행률
   API 연결 전이므로 저장·AI 처리는 화면 흐름만 흉내 냅니다(데모).
   ========================================================= */
(function ($, window, document) {
  'use strict';

  document.documentElement.classList.add('js');

  var SafeT = window.SafeT = window.SafeT || {};
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 화면(view) 전환 ---------- */
  var $defaultView = $();
  var pendingOpts = null;

  SafeT.currentView = function () {
    return $('.view.is-active').first();
  };

  SafeT.showView = function (id, opts) {
    var $v = $(document.getElementById(id));
    if (!$v.length || !$v.hasClass('view')) return;
    var $prev = SafeT.currentView();
    SafeT.closeModal(true);
    if ($prev[0] === $v[0]) {
      if (opts) $v.trigger('safet:show', [opts]);   // 같은 화면은 옵션이 있을 때만 다시 그림
      return;
    }
    $prev.removeClass('is-active').trigger('safet:hide');
    $v.addClass('is-active');
    window.scrollTo(0, 0);
    $v.trigger('safet:show', [opts || {}]);
    var h = $v.find('h1').get(0);
    if (h && !$v.get(0).contains(document.activeElement)) {   // 화면별 처리가 포커스를 옮겼으면 유지
      h.setAttribute('tabindex', '-1');
      h.focus({ preventScroll: true });
    }
  };

  /** 주소의 #id 를 바꿔 이동합니다. opts 는 화면 표시 이벤트(safet:show)로 전달됩니다. */
  SafeT.go = function (id, opts) {
    pendingOpts = opts || null;
    if (location.hash === '#' + id) {
      route();
    } else {
      location.hash = id;
    }
  };

  /** 링크 주소로 이동: '#id' 는 같은 페이지 안, 나머지는 페이지 이동 */
  SafeT.navigate = function (href) {
    if (!href) return;
    if (href.charAt(0) === '#') {
      SafeT.go(href.slice(1));
    } else {
      window.location.href = href;
    }
  };

  function route() {
    var id = decodeURIComponent(location.hash.slice(1));
    var el = id ? document.getElementById(id) : null;
    var $t = $(el);
    var opts = pendingOpts;
    pendingOpts = null;

    if ($t.hasClass('view')) {
      SafeT.showView(id, opts);
    } else if ($t.hasClass('modal')) {
      var $v = $t.closest('.view');
      if ($v.length) SafeT.showView($v.attr('id'), opts);
      SafeT.openModal($t);
    } else if (!id || !el) {
      if ($defaultView.length) SafeT.showView($defaultView.attr('id'), opts);
    }
  }

  /* ---------- 확인 창 ---------- */
  var lastFocus = null;

  SafeT.openModal = function (target) {
    var $m = typeof target === 'string' ? $(document.getElementById(target)) : $(target);
    if (!$m.length) return;
    $('.modal.is-open').not($m).removeClass('is-open');
    if (!$m.hasClass('is-open')) lastFocus = document.activeElement;
    $m.addClass('is-open').trigger('safet:open');
    if (!$m.hasClass('is-open')) return;          // 여는 중에 화면별 검사로 닫힌 경우
    $('body').addClass('has-modal');
    var first = $m.find('a[href], button:not(:disabled), input:not(:disabled), select, textarea').filter(':visible').get(0);
    if (first) first.focus();
  };

  /** quiet=true 면 포커스를 되돌리지 않습니다(화면 전환 중). */
  SafeT.closeModal = function (quiet) {
    var $m = $('.modal.is-open');
    if (!$m.length) return;
    $m.removeClass('is-open').trigger('safet:close');
    $('body').removeClass('has-modal');
    if (!quiet && lastFocus && document.contains(lastFocus)) lastFocus.focus();
    lastFocus = null;
  };

  /** 주소로 연 창이면 주소를 원래 화면으로 돌리고, JS로 연 창이면 그냥 닫습니다. */
  function dismissModal($m) {
    if ($m.is('[data-locked]')) return;
    var id = $m.attr('id');
    if (id && location.hash === '#' + id) {
      var vid = $m.closest('.view').attr('id');
      SafeT.go(vid || '');
    } else {
      SafeT.closeModal();
    }
  }

  /**
   * 확인 창 (confirm 대신 사용)
   * SafeT.confirm({ title, message, ok, cancel, danger, alt }).then(function (answer) { ... })
   * answer: true(ok) / false(cancel·닫기) / 'alt'(alt 버튼, 지정했을 때만)
   */
  SafeT.confirm = function (o) {
    var d = $.Deferred();
    var $m = $('#safet-confirm');
    if (!$m.length) {
      $m = $(
        '<div class="modal" id="safet-confirm" role="alertdialog" aria-modal="true" aria-labelledby="safet-confirm-title" aria-describedby="safet-confirm-msg">' +
        '  <div class="modal__box">' +
        '    <div class="modal__head"><h2 class="modal__title" id="safet-confirm-title"></h2></div>' +
        '    <div class="modal__body"><p id="safet-confirm-msg"></p></div>' +
        '    <div class="modal__foot">' +
        '      <button class="btn" type="button" data-answer="no"></button>' +
        '      <button class="btn" type="button" data-answer="alt" hidden></button>' +
        '      <button class="btn btn--primary" type="button" data-answer="yes"></button>' +
        '    </div>' +
        '  </div>' +
        '</div>'
      ).appendTo('body');
    }
    $m.find('#safet-confirm-title').text(o.title || '확인');
    $m.find('#safet-confirm-msg').text(o.message || '');
    $m.find('[data-answer="no"]').text(o.cancel || '취소');
    $m.find('[data-answer="alt"]').text(o.alt || '').prop('hidden', !o.alt);
    $m.find('[data-answer="yes"]').text(o.ok || '확인').toggleClass('btn--danger', !!o.danger).toggleClass('btn--primary', !o.danger);
    $m.off('.confirm')
      .on('click.confirm', '[data-answer]', function () {
        var a = $(this).data('answer');
        d.resolve(a === 'yes' ? true : (a === 'alt' ? 'alt' : false));   // 닫기 이벤트보다 먼저 답을 정함
        SafeT.closeModal();
      })
      .on('safet:close.confirm', function () {
        if (d.state() === 'pending') d.resolve(false);
      });
    SafeT.openModal($m);
    return d.promise();
  };

  /* ---------- 알림·로딩 ---------- */
  var toastTimer = null;

  SafeT.toast = function (msg, ms) {
    var $t = $('#safet-toast');
    if (!$t.length) {
      $t = $('<div class="toast" id="safet-toast" role="status" aria-live="polite"></div>').appendTo('body');
    }
    $t.text(msg).prop('hidden', false);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { $t.prop('hidden', true); }, ms || 2200);
  };

  /** 원형 로딩만 (데이터만 저장하는 동작). SafeT.loading(true) / SafeT.loading(false) */
  SafeT.loading = function (on) {
    var $l = $('#safet-loading');
    if (!$l.length) {
      $l = $('<div class="loading" id="safet-loading" role="status" aria-label="처리 중"><div class="spinner"></div></div>').appendTo('body');
    }
    $l.prop('hidden', !on);
  };

  /** 데모용 지연. API 연결 후에는 실제 요청 완료 시점으로 바꿉니다. */
  SafeT.wait = function (ms) {
    var d = $.Deferred();
    setTimeout(d.resolve, ms);
    return d.promise();
  };

  /**
   * 진행률 화면 (.progress-screen 안의 .ring · .bar · .strong · .steps-text 갱신)
   * steps: [{ pct: 20, label: '입력을 분석하고 있어요', step: '입력 분석' }, ...]
   * 반환값: 취소 함수. 실제로 끝나야 100% (API 연결 후 각 단계 완료 시점에 맞춥니다)
   */
  SafeT.runProgress = function ($root, o) {
    var $ring = $root.find('.ring');
    var $bar = $root.find('.bar');
    var $text = $root.find('.progress-screen > .strong');
    var $steps = $root.find('.steps-text');
    var timers = [];
    var cancelled = false;

    if (o.title) $root.find('.progress-screen h1').text(o.title);

    function set(i) {
      var s = o.steps[i];
      $ring.css('--value', s.pct).text(s.pct + '%').attr('aria-label', '진행률 ' + s.pct + '%');
      $bar.val(s.pct).text(s.pct + '%');
      $text.text(s.label);
      $steps.empty();
      $.each(o.steps, function (j, t) {
        if (j) $steps.append(' → ');
        $steps.append(j === i ? $('<strong>').text(t.step) : document.createTextNode(t.step));
      });
    }

    set(0);
    $.each(o.steps, function (i) {
      if (!i) return;
      timers.push(setTimeout(function () { if (!cancelled) set(i); }, i * (o.interval || 700)));
    });
    timers.push(setTimeout(function () {
      if (!cancelled && o.done) o.done();
    }, o.steps.length * (o.interval || 700)));

    return function cancel() {
      cancelled = true;
      $.each(timers, function (_, t) { clearTimeout(t); });
    };
  };

  /* ---------- 날짜 ---------- */
  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /** 한국 날짜 기준 오늘 (시각 없음) */
  SafeT.today = function () {
    var kst = new Date(Date.now() + 9 * 3600 * 1000);
    return new Date(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate());
  };

  /** 'YYYY.MM.DD' 또는 'YYYY-MM-DD' → Date. 잘못된 날짜면 null */
  SafeT.parseDate = function (s) {
    var m = /^\s*(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})\s*$/.exec(s || '');
    if (!m) return null;
    var d = new Date(+m[1], +m[2] - 1, +m[3]);
    if (d.getFullYear() !== +m[1] || d.getMonth() !== +m[2] - 1 || d.getDate() !== +m[3]) return null;
    return d;
  };

  SafeT.formatDate = function (d) {
    return d.getFullYear() + '.' + pad(d.getMonth() + 1) + '.' + pad(d.getDate());
  };

  /** 'MM.DD' 짧은 표시 */
  SafeT.shortDate = function (s) {
    var d = SafeT.parseDate(s);
    return d ? pad(d.getMonth() + 1) + '.' + pad(d.getDate()) : '';
  };

  function isDateInput(el) {
    return $(el).closest('.date-input').length > 0 && el.tagName === 'INPUT';
  }

  /* ---------- 입력 검사 ---------- */
  function errorAnchor($el) {
    var $a = $el.closest('.input-row, .date-input, .check');
    return $a.length ? $a : $el;
  }

  /** 입력칸 아래에 오류 문구를 표시합니다. */
  SafeT.fieldError = function (el, msg) {
    var $el = $(el);
    var $a = errorAnchor($el);
    $el.addClass('is-invalid').attr('aria-invalid', 'true');
    $a.nextAll('.js-error').first().remove();
    var id = 'err-' + Math.random().toString(36).slice(2, 8);
    $('<p class="error-text js-error" role="alert">').attr('id', id).text(msg).insertAfter($a);
    $el.attr('aria-describedby', id);
  };

  SafeT.clearError = function (el) {
    var $el = $(el);
    $el.removeClass('is-invalid').removeAttr('aria-invalid');
    var id = $el.attr('aria-describedby');
    if (id && id.indexOf('err-') === 0) {
      $(document.getElementById(id)).remove();
      $el.removeAttr('aria-describedby');
    }
  };

  SafeT.clearErrors = function ($scope) {
    $scope.find('.is-invalid').each(function () { SafeT.clearError(this); });
    $scope.find('.js-error').remove();
  };

  /** 기본 검사: required · type=email · minlength · 날짜 형식. 첫 오류 칸으로 포커스 */
  SafeT.validate = function ($form) {
    SafeT.clearErrors($form);
    var first = null;

    $form.find('input, select, textarea').filter(':visible').each(function () {
      var el = this;
      var $el = $(el);
      var val = $.trim($el.val() || '');
      var msg = '';

      if (el.type === 'checkbox' || el.type === 'radio') {
        if (el.required && !$form.find('[name="' + el.name + '"]:checked').length) {
          msg = el.type === 'checkbox' ? '확인 체크가 필요해요.' : '하나를 선택해 주세요.';
        }
      } else if (el.required && !val) {
        msg = '필수 입력이에요.';
      } else if (val && el.type === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val)) {
        msg = '이메일 형식을 확인해 주세요.';
      } else if (val && el.minLength > 0 && val.length < el.minLength) {
        msg = el.minLength + '자 이상 입력해 주세요.';
      } else if (val && isDateInput(el) && !SafeT.parseDate(val)) {
        msg = '날짜를 YYYY.MM.DD 형식으로 입력해 주세요.';
      } else if (val && isDateInput(el) && $el.data('max') === 'today' && SafeT.parseDate(val) > SafeT.today()) {
        msg = '오늘 또는 지난 날짜만 입력할 수 있어요.';
      }

      if (msg) {
        SafeT.fieldError(el, msg);
        if (!first) first = el;
      }
    });

    // 화면별 추가 검사: $form.on('safet:validate', function (e) { ... e.preventDefault(); })
    var ev = $.Event('safet:validate');
    $form.trigger(ev);
    if (ev.isDefaultPrevented() && !first) {
      first = $form.find('.is-invalid').get(0) || null;
      if (!first) return false;
    }
    if (first) {
      first.focus();
      return false;
    }
    return true;
  };

  /* ---------- 작은 달력 (입력칸 1개 + 달력 1개) ---------- */
  var DOW = ['일', '월', '화', '수', '목', '금', '토'];

  function closeCalendars() {
    $('.mini-cal').remove();
  }

  function renderCalendar($wrap, base) {
    var $input = $wrap.find('input').first();
    var selected = SafeT.parseDate($input.val());
    var today = SafeT.today();
    var max = $input.data('max') === 'today' ? today : null;
    var y = base.getFullYear();
    var m = base.getMonth();

    var $cal = $wrap.find('.mini-cal');
    if (!$cal.length) {
      $cal = $('<div class="mini-cal" role="dialog" aria-label="달력">').appendTo($wrap);
    }
    $cal.empty().data('base', base);

    var $head = $('<div class="mini-cal__head">').appendTo($cal);
    $('<button type="button" data-cal="prev" aria-label="이전 달">‹</button>').appendTo($head);
    $('<span class="strong">').text(y + '년 ' + (m + 1) + '월').appendTo($head);
    $('<button type="button" data-cal="next" aria-label="다음 달">›</button>').appendTo($head);

    var $grid = $('<div class="mini-cal__grid">').appendTo($cal);
    $.each(DOW, function (_, d) { $('<span>').text(d).appendTo($grid); });
    var firstDow = new Date(y, m, 1).getDay();
    var days = new Date(y, m + 1, 0).getDate();
    for (var i = 0; i < firstDow; i++) $('<span>').appendTo($grid);
    for (var d = 1; d <= days; d++) {
      var date = new Date(y, m, d);
      var $b = $('<button type="button" data-cal="day">').text(d).data('date', date)
        .attr('aria-label', y + '년 ' + (m + 1) + '월 ' + d + '일');
      if (selected && +selected === +date) $b.attr('aria-pressed', 'true');
      if (+date === +today) $b.addClass('is-today');
      if (max && date > max) $b.prop('disabled', true);
      $b.appendTo($grid);
    }

    var $foot = $('<div class="mini-cal__foot">').appendTo($cal);
    $('<button type="button" class="link small" data-cal="today">오늘</button>').appendTo($foot);
    $('<button type="button" class="link small" data-cal="close">닫기</button>').appendTo($foot);

    // 아래 공간이 부족하면 위로 엽니다.
    $cal.removeClass('mini-cal--up');
    var rect = $cal.get(0).getBoundingClientRect();
    if (rect.bottom > window.innerHeight && $wrap.get(0).getBoundingClientRect().top > rect.height) {
      $cal.addClass('mini-cal--up');
    }
  }

  function openCalendar($wrap) {
    closeCalendars();
    var v = SafeT.parseDate($wrap.find('input').val());
    renderCalendar($wrap, v || SafeT.today());
    var $focus = $wrap.find('[aria-pressed="true"], .is-today').first();
    ($focus.length ? $focus : $wrap.find('[data-cal="day"]').first()).trigger('focus');
  }

  /* ---------- 이벤트 연결 ---------- */
  $(function () {
    $defaultView = $('.view.is-active').first();
    if (location.hash) route();
    $(window).on('hashchange', route);

    // 비활성 링크 막기
    $(document).on('click', 'a[aria-disabled="true"]', function (e) { e.preventDefault(); });

    // 아직 연결 전인 기능: <button data-todo="안내 문구">
    $(document).on('click', '[data-todo]', function (e) {
      e.preventDefault();
      SafeT.toast($(this).data('todo'));
    });

    // 상단 메뉴: 바깥 클릭·Esc 로 닫기
    $(document).on('click', function (e) {
      $('details.menu[open]').each(function () {
        if (!this.contains(e.target)) this.open = false;
      });
      if (!$(e.target).closest('.date-input').length) closeCalendars();
    });

    // 확인 창: 바깥 영역·[data-close] 로 닫기
    $(document).on('click', '.modal', function (e) {
      if (e.target === this) dismissModal($(this));
    });
    $(document).on('click', '[data-close]', function (e) {
      e.preventDefault();
      dismissModal($(this).closest('.modal'));
    });

    $(document).on('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if ($('.mini-cal').length) {            // Esc 는 달력만 먼저 닫음
        var $w = $('.mini-cal').closest('.date-input');
        closeCalendars();
        $w.find('input').trigger('focus');
        return;
      }
      var $m = $('.modal.is-open').last();
      if ($m.length) { dismissModal($m); return; }
      $('details.menu[open]').each(function () {
        this.open = false;
        $(this).find('summary').trigger('focus');
      });
    });

    // 입력하면 오류 표시 지우기
    // (텍스트 칸은 'input' 때만: 포커스가 빠질 때 지우면 화면이 밀려 누르려던 버튼이 빗나감)
    $(document).on('input', '.is-invalid', clearOnEdit);
    $(document).on('change', 'select.is-invalid, input[type="checkbox"].is-invalid, input[type="radio"].is-invalid', clearOnEdit);
    function clearOnEdit() {
      SafeT.clearError(this);
      $(this).closest('.check-list, .section').removeClass('is-invalid');
    }

    // 폼 제출: 검사 → 화면별 처리(safet:submit) → action 으로 이동
    $(document).on('submit', 'form', function (e) {
      var $f = $(this);
      e.preventDefault();
      if (!SafeT.validate($f)) return;
      var ev = $.Event('safet:submit');
      $f.trigger(ev);
      if (ev.isDefaultPrevented()) return;
      var href = $f.attr('action') || '';
      if ($f.is('[data-loading]')) {      // 데이터만 저장: 원형 로딩만
        SafeT.loading(true);
        SafeT.wait(500).then(function () {
          SafeT.loading(false);
          SafeT.navigate(href);
        });
      } else {
        SafeT.navigate(href);
      }
    });

    // 엔터 키로 '추가' 버튼 누르기: <input data-enter="#버튼">
    $(document).on('keydown', 'input[data-enter]', function (e) {
      if (e.key === 'Enter' && !e.isComposing) {
        e.preventDefault();
        $($(this).data('enter')).trigger('click');
      }
    });

    // 달력
    $(document).on('click', '.date-input__icon', function (e) {
      e.stopPropagation();
      var $w = $(this).closest('.date-input');
      if ($w.find('.mini-cal').length) closeCalendars(); else openCalendar($w);
    });
    $(document).on('click', '.mini-cal [data-cal]', function (e) {
      e.stopPropagation();
      var $b = $(this);
      var $cal = $b.closest('.mini-cal');
      var $w = $cal.closest('.date-input');
      var $input = $w.find('input').first();
      var base = $cal.data('base');
      switch ($b.data('cal')) {
        case 'prev': renderCalendar($w, new Date(base.getFullYear(), base.getMonth() - 1, 1)); $w.find('[data-cal="prev"]').trigger('focus'); break;
        case 'next': renderCalendar($w, new Date(base.getFullYear(), base.getMonth() + 1, 1)); $w.find('[data-cal="next"]').trigger('focus'); break;
        case 'today': renderCalendar($w, SafeT.today()); break;
        case 'close': closeCalendars(); $input.trigger('focus'); break;
        case 'day':
          $input.val(SafeT.formatDate($b.data('date'))).trigger('change');
          closeCalendars();
          $input.trigger('focus');
          break;
      }
    });
    // 날짜 입력칸: 칸을 벗어나면 형식 검사
    $(document).on('blur', '.date-input input', function () {
      var v = $.trim(this.value);
      if (!v) return;
      var d = SafeT.parseDate(v);
      if (!d) {
        SafeT.fieldError(this, '날짜를 YYYY.MM.DD 형식으로 입력해 주세요.');
      } else {
        this.value = SafeT.formatDate(d);   // YYYY-MM-DD 도 YYYY.MM.DD 로 맞춤
      }
    });
  });

  SafeT.reduceMotion = reduceMotion;
})(jQuery, window, document);
