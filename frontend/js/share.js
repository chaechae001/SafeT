/* =========================================================
   결과 공유 (share.html) · 받는 사람 화면 (share-download.html) · SHARE · 화면설계서 30쪽
   - 평가표당 링크 1개(7일). 공유 중지·재발급 시 이전 링크는 바로 막힘
   - 앱 안에서 메신저로 직접 보내지 않음(링크 복사·QR)
   - 열람·다운로드는 결과 확인·서명으로 기록하지 않음(다운로드 횟수만)
   API (backend/routers/share.py)
     공유하는 사람(로그인): GET·POST /evals/{번호}/share · POST …/share/reissue · POST …/share/stop
     받는 사람(로그인 없음): GET /share/{토큰} · GET /share/{토큰}/pdf
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  function when(iso) {                      // '2026-11-24T12:30:00' → '2026.11.24 12:30'
    if (!iso) return '';
    var s = String(iso);
    return s.slice(0, 10).replace(/-/g, '.') + (s.length > 15 ? ' ' + s.slice(11, 16) : '');
  }
  function day(iso) { return iso ? String(iso).slice(0, 10).replace(/-/g, '.') : '—'; }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // 대체: 입력칸 선택 후 복사
    var $tmp = $('<textarea class="sr-only">').val(text).appendTo('body');
    $tmp.get(0).select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    $tmp.remove();
    return ok ? Promise.resolve() : Promise.reject();
  }

  /* ---------- 공유하는 사람 (share.html) ---------- */
  function sharePage() {
    var evalNo = Number(new URLSearchParams(location.search).get('eval')) || (SafeT.current && SafeT.current.evalNo());
    var busy = false;

    function render(res) {
      $('.js-eval-nm').text(res.eval_nm || '평가표');
      $('#item-count').text(res.item_count);
      var s = res.share;
      $('#share-on, #reissue-link').prop('hidden', !s);
      $('#share-off').prop('hidden', !!s || res.status === 'none');   // 처음(만든 적 없음)엔 '중지' 안내를 띄우지 않음
      if (!s) {
        $('#share_url').val('');
        $('#qr-box').removeClass('qr-box--ready').text('QR');
        if (res.status === 'expired') {
          $('#share-off-title').text('공유 링크가 만료되었어요.');
          $('#share-off-desc').text('7일이 지나 이전 링크는 열리지 않아요. 다시 공유하려면 새 링크를 발급해 주세요.');
        } else {
          $('#share-off-title').text('공유를 중지했어요.');
          $('#share-off-desc').text('이전 링크는 열리지 않아요. 다시 공유하려면 새 링크를 발급해 주세요.');
        }
        return;
      }
      $('#share_url').val(s.url);
      $('#share-expire').text(when(s.expire_dt) + '까지 유효 (7일) · 로그인 없이 열림');
      $('#share-count').text('내려받은 횟수 ' + s.download_cnt + '회');
      // 서버(segno)가 만든 QR SVG. 같은 링크 주소로 만듦
      $('#qr-box').addClass('qr-box--ready').html(s.qr_svg);
    }

    function call(method, path, okMsg) {
      if (busy) return $.Deferred().reject().promise();
      busy = true;
      SafeT.loading(true);
      return SafeT.api[method](path).done(function (res) {
        render(res);
        if (okMsg) SafeT.toast(okMsg);
      }).fail(function (err) {
        SafeT.toast(err.message);
        if (err.code === 'SIGN_NOT_DONE' || err.status === 404) {
          setTimeout(function () { window.location.href = 'home.html'; }, 1400);
        }
      }).always(function () {
        busy = false;
        SafeT.loading(false);
      });
    }

    if (!evalNo) {
      SafeT.toast('내 평가표에서 평가표를 다시 골라 주세요.');
      setTimeout(function () { window.location.href = 'home.html'; }, 1200);
      return;
    }
    if (SafeT.current) SafeT.current.setEval(evalNo);

    // 처음 열 때: 조회만. 링크를 만든 적이 없을 때(status=none)만 바로 발급 (설계서 30쪽 '결과 공유를 누르면 링크 생성')
    // 중지·만료된 뒤에는 자동으로 만들지 않고 '새 링크 발급' 버튼으로만 (2026-11-17 결정)
    call('get', '/evals/' + evalNo + '/share').done(function (res) {
      if (res.status === 'none') call('post', '/evals/' + evalNo + '/share');
    });

    $('#copy-link').on('click', function () {
      var url = $('#share_url').val();
      if (!url) return;
      copyText(url).then(function () {
        SafeT.toast('링크를 복사했어요. 메신저에 붙여 넣어 보내 주세요.');
      }, function () {
        $('#share_url').trigger('focus').get(0).select();
        SafeT.toast('복사하지 못했어요. 선택된 링크를 직접 복사해 주세요.');
      });
    });

    $('#share-stop').on('click', function () {
      SafeT.closeModal(true);
      SafeT.go('v-share');
      call('post', '/evals/' + evalNo + '/share/stop', '공유를 중지했어요. 이전 링크는 열리지 않아요.');
    });

    $('#share-reissue').on('click', function () {
      SafeT.closeModal(true);
      SafeT.go('v-share');
      call('post', '/evals/' + evalNo + '/share/reissue', '새 링크를 발급했어요. 이전 링크는 열리지 않아요.');
    });

    $('#share-new').on('click', function () {
      call('post', '/evals/' + evalNo + '/share', '새 링크를 발급했어요.');
    });
  }

  /* ---------- 받는 사람 (share-download.html · 로그인 없음) ---------- */
  function downloadPage() {
    var token = new URLSearchParams(location.search).get('t') || '';
    var busy = false;

    function expired() {
      $('#dl-loading, #dl-info, #dl-file, #dl-expire').prop('hidden', true);
      $('#dl-expired').prop('hidden', false);
      $('#pdf-download').prop('disabled', true).prop('hidden', true);
    }

    if (!token) { expired(); return; }

    SafeT.api.get('/share/' + encodeURIComponent(token)).done(function (r) {
      document.title = r.eval_nm + ' · Safe-T';
      $('#dl-title').text(r.eval_nm);
      $('#dl-workplace').text(r.workplace || '—');
      $('#dl-eval-dt').text(day(r.eval_dt));
      $('#dl-confirm-dt').text(day(r.confirm_dt));
      $('#dl-items').text(r.item_count + '건');
      $('#dl-writer').text(r.eval_writer || '—');
      $('#dl-file-nm').text(r.file_nm);
      $('#dl-expire').text('이 링크는 ' + when(r.expire_dt) + '까지 열 수 있어요.');
      $('#dl-loading').prop('hidden', true);
      $('#dl-info, #dl-file, #dl-expire').prop('hidden', false);
      $('#pdf-download').prop('disabled', false);
    }).fail(function (err) {
      if (err.code === 'SHARE_EXPIRED' || err.status === 410) { expired(); return; }
      $('#dl-loading').text(err.message);
    });

    $('#pdf-download').on('click', function () {
      if (busy) return;
      busy = true;
      SafeT.loading(true);
      SafeT.api.download('/share/' + encodeURIComponent(token) + '/pdf')
        .done(function () { SafeT.toast('PDF를 내려받았어요.'); })
        .fail(function (err) {
          if (err.code === 'SHARE_EXPIRED' || err.status === 410) expired();
          SafeT.toast(err.message);
        })
        .always(function () { busy = false; SafeT.loading(false); });
    });
  }

  $(function () {
    if ($('#v-share').length) sharePage();
    if ($('#v-download').length) downloadPage();
  });
})(jQuery, window.SafeT);
