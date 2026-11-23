/* =========================================================
   위험도 판단 이유를 쉬운 말로
   서버가 만드는 계산 설명
     "FOOD-3LEVEL-1.2 · 피해 S3(사망·중상 가능) · 핵심 일부 또는 전부 미충족 → 상. 반영한 기준 조치: 없음.
      남은 핵심 조치: MIX-C1, MIX-C2. 남은 보완 조치: MIX-C4. 남은 핵심 조치를 충족하면 중입니다."
   를 화면에서만 사용자 문장으로 바꿉니다. 정책 이름·조치 ID는 보이지 않게 하고, ID는 조치 이름으로 바꿉니다.
   형식이 다르면 원문을 그대로 돌려줍니다(정보를 숨기지 않음). 서버 값과 계산은 바꾸지 않습니다.
   ========================================================= */
(function (S) {
  'use strict';
  var BAND = {
    '기준 조치 전체 충족': '기준 안전조치를 모두 하고 있어',
    '핵심 전부 충족·보완 일부 미충족': '꼭 필요한 조치는 했지만 보완 조치가 일부 빠져',
    '핵심 일부 또는 전부 미충족': '꼭 필요한 안전조치 중 빠진 것이 있어'
  };
  var SEV = { '경미·응급처치': '다쳐도 가벼운 응급처치로 끝나는 일이에요.', '휴업 부상·질병 가능': '일을 쉬어야 할 만큼 다칠 수 있는 일이에요.', '사망·중상 가능': '크게 다치거나 목숨을 잃을 수도 있는 일이에요.' };
  function ro(g) { return "'" + g + "'" + (g === '하' ? '로' : '으로'); }

  /** @param reason 서버 설명, @param controls it.catalog.scenario.controls (조치 ID → 이름) */
  function friendly(reason, controls) {
    if (!reason) return '';
    var text = String(reason);
    var pre = '';
    var assume = /계획 이행·효과를 가정한 예상/.test(text);
    if (assume) pre = '고른 대책을 모두 했다고 가정한 예상이에요(실제 결과 아님). ';
    var m = /피해 S\d\(([^)]+)\)\s*·\s*([^→]+?)\s*→\s*(상|중|하)/.exec(text);
    if (!m) {
      var old = /피해 S\d\s*·\s*조치 C\d\s*→\s*(상|중|하)/.exec(text);   // 1.1 형식
      if (old) return pre + '선택한 현재 조치를 기준으로 ' + ro(old[1]) + ' 판단했어요.';
      return text;                                                     // 다른 형식은 원문 그대로
    }
    var out = [];
    var sev = SEV[m[1].trim()];
    if (sev) out.push(sev);
    out.push((BAND[m[2].trim()] || '선택한 조치를 기준으로') + ' ' + ro(m[3]) + ' 판단했어요.');
    var core = /남은 핵심 조치:\s*([^.]+)\./.exec(text);
    // 펼침 설명에서도 '아직 안 된 꼭 필요한 조치: ○○' 문장은 숨김(요약 카드 코멘트와 같은 표현). 서버 설명 원문·계산은 그대로
    var up = /충족하면 (상|중|하)입니다/.exec(text);
    var keep = /충족해도 판정표상 (상|중|하)가 유지/.exec(text);
    if (up) out.push('남은 조치를 하면 ' + ro(up[1]) + ' 낮아져요.');
    else if (keep) out.push("남은 조치를 해도 위험의 크기 때문에 '" + keep[1] + "'" + (keep[1] === '하' ? '가' : '이') + ' 유지돼요.');
    return pre + out.join(' ');
  }

  /** 요약 카드용 구조 값 {grade:'상', core:['조치 이름',…], next:'중'|null, keep:'상'|null} · 형식이 다르면 null */
  function parse(reason, controls) {
    if (!reason) return null;
    var text = String(reason);
    var m = /→\s*(상|중|하)/.exec(text);
    if (!m) return null;
    var map = {};
    (controls || []).forEach(function (c) { map[c.id] = c.current_text || c.text || c.id; });
    var core = /남은 핵심 조치:\s*([^.]+)\./.exec(text);
    var list = core ? core[1].split(',').map(function (s) { return map[s.trim()]; }).filter(Boolean) : [];
    var up = /충족하면 (상|중|하)입니다/.exec(text), keep = /충족해도 판정표상 (상|중|하)가 유지/.exec(text);
    return { grade: m[1], core: list, next: up ? up[1] : null, keep: keep ? keep[1] : null };
  }

  S.riskText = { friendly: friendly, parse: parse, ro: ro };
})(window.SafeT = window.SafeT || {});
