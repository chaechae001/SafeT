/* =========================================================
   새 평가표 작성 (write.html) · S01 기본정보 · S02 현장입력 · S03 보유기기 · S04 초안 생성
   API 연결 전: 입력값은 화면 안에서만 유지하고 저장하지 않습니다.
   ========================================================= */
(function ($, SafeT) {
  'use strict';

  $(function () {
    // 새 평가표: 이전에 보던 평가표 번호가 남아 있지 않게 비움 (SafeT.current · api.js)
    if (SafeT.current) SafeT.current.setEval(null);

    /* ---------- S01 기본정보 ---------- */
    var $memberInput = $('#member_add');
    var $memberList = $('#v-basic .name-tags');

    // 평가일 처음 값: 한국 기준 오늘(제안값)
    if (!$('#eval_dt').val()) $('#eval_dt').val(SafeT.formatDate(SafeT.today()));

    function memberNames() {
      return $memberList.find('input[name="member_nm"]').map(function () { return this.value; }).get();
    }

    $('#member-add-btn').on('click', function () {
      var name = $.trim($memberInput.val()).replace(/\s+/g, ' ');
      SafeT.clearError($memberInput);
      if (!name) {
        SafeT.fieldError($memberInput, '이름을 입력해 주세요.');
        $memberInput.trigger('focus');
        return;
      }
      if ($.inArray(name, memberNames()) > -1) {
        SafeT.fieldError($memberInput, '이미 추가한 이름이에요.');
        $memberInput.trigger('focus');
        return;
      }
      var $li = $('<li class="name-tag">').text(name);
      $('<button type="button">×</button>').attr('aria-label', name + ' 삭제').appendTo($li);
      $('<input type="hidden" name="member_nm">').val(name).appendTo($li);
      $memberList.append($li);
      $memberInput.val('').trigger('focus');
    });

    $memberList.on('click', 'button', function () {
      $(this).closest('.name-tag').remove();
      $memberInput.trigger('focus');
    });

    // 사업장을 바꾸면 03 보유기기의 등록 기기를 다시 확인해야 함
    $('#work_no').on('change', function () {
      $('#v-equipment').data('needRecheck', true);
    });

    /* ---------- S02 현장입력 ---------- */
    var $photoGrid = $('#v-field .photo-grid');
    var photoSeq = $photoGrid.children().length;

    function renumberPhotos() {
      $photoGrid.children('.photo').each(function (i) {
        var n = i + 1;
        $(this).find('.photo__remove').attr('aria-label', '사진 ' + n + ' 삭제');
        $(this).find('label').text('사진 ' + n + ' 장소');
      });
    }

    $('#photo-input').on('change', function () {
      $.each(this.files || [], function (_, file) {
        if (!/^image\//.test(file.type)) return;
        photoSeq += 1;
        var id = 'place_nm_' + photoSeq;
        var $li = $('<li class="photo">');
        $('<img class="photo__img" alt="">').attr('src', URL.createObjectURL(file)).appendTo($li);
        $('<button class="photo__remove" type="button">×</button>').appendTo($li);
        $('<label class="sr-only">').attr('for', id).appendTo($li);
        $('<input class="input" name="place_nm" maxlength="100" placeholder="장소 입력">').attr('id', id).appendTo($li);
        $photoGrid.append($li);
      });
      this.value = '';
      renumberPhotos();
    });

    $photoGrid.on('click', '.photo__remove', function () {
      var $img = $(this).siblings('img');
      if ($img.length) URL.revokeObjectURL($img.attr('src'));
      $(this).closest('.photo').remove();
      renumberPhotos();
    });

    // 음성 카드 X: 오디오와 전사문만 삭제 (사진·직접 설명은 그대로)
    $('#v-field .voice-card__remove').on('click', function () {
      $(this).closest('.voice-card').remove();
      $('#file_text').trigger('focus');
    });

    // 녹음은 마이크 권한·전사 API 연결 후 동작
    $('#voice-btn').on('click', function () {
      SafeT.toast('음성 녹음은 API 연결 후 동작해요. 사진이나 글로 입력해 주세요.');
    });

    // 최소 입력: 사진·직접 설명·음성 전사문 중 하나 이상
    $('#field-form').on('safet:validate', function (e) {
      var hasPhoto = $photoGrid.children('.photo').length > 0;
      var hasText = $.trim($('#file_text').val()) !== '';
      var hasVoice = $.trim($('#voice_text').val() || '') !== '';
      if (!hasPhoto && !hasText && !hasVoice) {
        e.preventDefault();
        SafeT.fieldError($('#file_text'), '사진·음성·글 중 하나 이상 입력해 주세요.');
      }
    });

    /* ---------- S03 보유기기 ---------- */
    $('#v-equipment').on('safet:show', function () {
      if ($(this).data('needRecheck')) {
        SafeT.toast('사업장이 바뀌어 보유기기를 다시 확인해 주세요.');
        $(this).data('needRecheck', false);
      }
    });

    /* ---------- S04 초안 생성 (진행률) ---------- */
    var cancelGenerate = null;

    $('#v-generating')
      .on('safet:show', function () {
        if (cancelGenerate) cancelGenerate();
        cancelGenerate = SafeT.runProgress($(this), {
          steps: [
            { pct: 20, step: '입력 분석', label: '입력을 분석하고 있어요' },
            { pct: 40, step: '위험 항목 생성', label: '위험 항목을 만들고 있어요' },
            { pct: 60, step: '위험 신호 판단', label: '위험 신호를 판단하고 있어요' },
            { pct: 80, step: '대책 추천', label: '대책을 추천하고 있어요' },
            { pct: 100, step: '초안 저장', label: '초안을 저장했어요' }
          ],
          done: function () { window.location.href = 'draft.html'; }
        });
      })
      .on('safet:hide', function () {
        // 입력으로 돌아가면 늦게 온 응답이 화면을 바꾸지 않도록 요청 취소
        if (cancelGenerate) cancelGenerate();
        cancelGenerate = null;
      });
  });
})(jQuery, window.SafeT);
