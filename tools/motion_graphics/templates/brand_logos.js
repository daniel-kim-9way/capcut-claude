/* brand_logos.js — 진짜 브랜드 SVG 로고 레지스트리 (TL-04, 2026-06-04)
 *
 * 목적:
 *   logo_marquee / icon_hero / orbiting_circles 가 단일 글자 이니셜 타일
 *   ("N", "S", "G" …) 대신 진짜 브랜드 SVG 로고를 그릴 수 있게 한다.
 *   ("색 스와치 보드처럼 촌스럽다" 불만 → 실제 로고로 격상)
 *
 * 사용:
 *   <script src="brand_logos.js"></script>  (shared.css 와 동일하게 file:// 상대경로 로드)
 *   const entry = window.BRAND_LOGOS["claude"];
 *   // entry = { name, color, bg, svg(viewBox 포함 <svg>...</svg> 문자열), fg }
 *
 * 하위호환:
 *   미등록 브랜드는 null → 소비 템플릿이 기존 이니셜 타일로 폴백.
 *   기존 params(symbol/bg/color) 동작은 그대로 보존된다.
 *
 * 저작권/정확성:
 *   단순 기하 path만, 잘 아는 브랜드만 정확 복제. 모르면 등록하지 말고 폴백.
 * chroma:
 *   렌더 배경이 #0000FF(크로마 블루)이므로 순수 파랑(#0000FF) 근처색은
 *   카드 bg/로고 색에서 회피한다. Discord(#5865F2)·Slack 파랑 계열도
 *   #0000FF 와 충분히 떨어져 있어 안전(카드 bg 위에 그려지므로 직접 밟지 않음).
 */
(function () {
  "use strict";

  // 각 entry:
  //   name  : 라벨 기본값
  //   bg    : 로고가 놓일 카드 배경색 (브랜드 분위기색)
  //   color : 마퀴/오비트 라벨·이니셜 폴백 텍스트 색
  //   fg    : 단색 글리프 로고일 때 path fill 기본색 (svg 내부에서 currentColor 사용 시)
  //   svg(fg): viewBox 포함한 완전한 <svg> 문자열을 반환하는 함수.
  //            컨테이너가 width/height 를 제어하므로 svg 자체엔 px 크기를 강제하지 않는다.
  var REGISTRY = {

    // ---- Claude (Anthropic starburst) — icon_claude_1x1 검증 path 재사용 ----
    claude: {
      name: "Claude",
      bg: "#FAF7F2",          // Anthropic warm white
      color: "#D97757",
      fg: "#D97757",          // Claude signature orange
      svg: function (fg) {
        var color = fg || this.fg;
        var arms = "";
        var angles = [0, 45, 90, 135, 180, 225, 270, 315];
        for (var i = 0; i < angles.length; i++) {
          arms += '<use href="#bl-claude-arm" fill="' + color +
            '" transform="rotate(' + angles[i] + ' 50 50)" />';
        }
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%;overflow:visible">' +
          '<defs><path id="bl-claude-arm" d="M 50 5 Q 53 25 50 50 Q 47 25 50 5 Z" /></defs>' +
          arms + '</svg>';
      },
    },

    // ---- ChatGPT / OpenAI (6-petal knot 근사) — dual_brand 검증 path 재사용 ----
    chatgpt: {
      name: "ChatGPT",
      bg: "#FFFFFF",
      color: "#10A37F",
      fg: "#10A37F",          // OpenAI teal
      svg: function (fg) {
        var color = fg || this.fg;
        var petals = "";
        var angles = [0, 60, 120, 180, 240, 300];
        for (var i = 0; i < angles.length; i++) {
          petals += '<use href="#bl-gpt-petal" fill="' + color +
            '" transform="rotate(' + angles[i] + ' 50 50)" />';
        }
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%;overflow:visible">' +
          '<defs><path id="bl-gpt-petal" d="M 50 8 C 60 22 60 38 50 50 C 40 38 40 22 50 8 Z" /></defs>' +
          petals + '</svg>';
      },
    },

    // ---- Notion (둥근 사각 + N 모노그램 path) ----
    notion: {
      name: "Notion",
      bg: "#FFFFFF",
      color: "#191919",
      fg: "#191919",
      svg: function (fg) {
        var color = fg || this.fg;
        // N 모노그램: 좌측 세로획 + 대각선 + 우측 세로획 (한붓 외곽선)
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          '<path fill="' + color + '" d="M 26 24 L 36 24 L 64 62 L 64 24 L 74 24 ' +
          'L 74 76 L 64 76 L 36 38 L 36 76 L 26 76 Z" /></svg>';
      },
    },

    // ---- Slack (4-color 해시 클로버) ----
    slack: {
      name: "Slack",
      bg: "#FFFFFF",
      color: "#4A154B",
      fg: "#4A154B",
      svg: function () {
        // 4색 4쌍 알약 — Slack 공식 컬러(크로마블루와 충분히 분리)
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          // green pair (좌하)
          '<rect x="30" y="58" width="12" height="30" rx="6" fill="#2EB67D"/>' +
          '<rect x="12" y="58" width="30" height="12" rx="6" fill="#2EB67D"/>' +
          // blue pair (우하)
          '<rect x="58" y="58" width="12" height="30" rx="6" fill="#36C5F0"/>' +
          '<rect x="58" y="58" width="30" height="12" rx="6" fill="#36C5F0"/>' +
          // yellow pair (우상)
          '<rect x="58" y="12" width="12" height="30" rx="6" fill="#ECB22E"/>' +
          '<rect x="58" y="30" width="30" height="12" rx="6" fill="#ECB22E"/>' +
          // red pair (좌상)
          '<rect x="30" y="12" width="12" height="30" rx="6" fill="#E01E5A"/>' +
          '<rect x="12" y="30" width="30" height="12" rx="6" fill="#E01E5A"/>' +
          '</svg>';
      },
    },

    // ---- Discord (말풍선 + 2 eyes 근사) ----
    discord: {
      name: "Discord",
      bg: "#5865F2",          // Blurple (≠ #0000FF, 안전)
      color: "#FFFFFF",
      fg: "#FFFFFF",
      svg: function (fg) {
        var color = fg || this.fg;
        // 둥근 게임패드형 말풍선 + 두 눈
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          '<path fill="' + color + '" d="M 24 30 Q 50 22 76 30 ' +
          'Q 86 50 84 70 Q 72 80 62 80 L 58 73 Q 70 70 74 64 ' +
          'Q 62 70 50 70 Q 38 70 26 64 Q 30 70 42 73 L 38 80 ' +
          'Q 28 80 16 70 Q 14 50 24 30 Z" />' +
          '<ellipse cx="40" cy="52" rx="6" ry="8" fill="#5865F2"/>' +
          '<ellipse cx="60" cy="52" rx="6" ry="8" fill="#5865F2"/></svg>';
      },
    },

    // ---- GitHub (Octocat 실루엣 단순화) / 단색 mark ----
    github: {
      name: "GitHub",
      bg: "#0D1117",
      color: "#FFFFFF",
      fg: "#FFFFFF",
      svg: function (fg) {
        var color = fg || this.fg;
        // 둥근 몸통 + 두 귀 + 꼬리 (단색 octocat 근사)
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          '<path fill="' + color + '" d="M 50 16 ' +
          'C 31 16 16 31 16 50 C 16 65 26 78 40 83 ' +
          'C 42 83 43 82 43 81 L 43 74 C 33 76 31 69 31 69 ' +
          'C 29 65 27 64 27 64 C 24 62 28 62 28 62 ' +
          'C 31 62 33 65 33 65 C 36 70 41 68 43 67 ' +
          'C 43 65 44 63 45 62 C 37 61 29 58 29 45 ' +
          'C 29 41 30 38 33 35 C 32 34 31 30 33 26 ' +
          'C 33 26 37 25 43 29 C 47 28 53 28 57 29 ' +
          'C 63 25 67 26 67 26 C 69 30 68 34 67 35 ' +
          'C 70 38 71 41 71 45 C 71 58 63 61 55 62 ' +
          'C 56 63 57 66 57 70 L 57 81 C 57 82 58 83 60 83 ' +
          'C 74 78 84 65 84 50 C 84 31 69 16 50 16 Z" /></svg>';
      },
    },

    // ---- Figma (5-blob 컬러 마크) ----
    figma: {
      name: "Figma",
      bg: "#FFFFFF",
      color: "#1E1E1E",
      fg: "#1E1E1E",
      svg: function () {
        // 좌측 3원(상/중/하) + 우상 원 + 중앙 원 — Figma 공식 5색
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          // top-left (red)
          '<path fill="#F24E1E" d="M 36 18 L 50 18 L 50 41 L 36 41 ' +
          'A 11.5 11.5 0 0 1 36 18 Z"/>' +
          // top-right (orange)
          '<path fill="#FF7262" d="M 50 18 L 61 18 A 11.5 11.5 0 0 1 61 41 ' +
          'L 50 41 Z"/>' +
          // mid-left (purple)
          '<path fill="#A259FF" d="M 36 41 L 50 41 L 50 64 L 36 64 ' +
          'A 11.5 11.5 0 0 1 36 41 Z"/>' +
          // center circle (green)
          '<circle cx="61" cy="52" r="11.5" fill="#0ACF83"/>' +
          // bottom-left (blue) — 둥근 끝
          '<path fill="#1ABCFE" d="M 36 64 L 50 64 L 50 76 ' +
          'A 11.5 11.5 0 1 1 36 64 Z"/></svg>';
      },
    },

    // ---- YouTube (rounded-rect + play triangle) ----
    youtube: {
      name: "YouTube",
      bg: "#FFFFFF",
      color: "#FF0000",
      fg: "#FF0000",
      svg: function (fg) {
        var color = fg || this.fg;
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          '<rect x="14" y="30" width="72" height="40" rx="12" fill="' + color + '"/>' +
          '<path fill="#FFFFFF" d="M 44 40 L 62 50 L 44 60 Z"/></svg>';
      },
    },

    // ---- Gmail (envelope 'M' 컬러 마크) ----
    gmail: {
      name: "Gmail",
      bg: "#FFFFFF",
      color: "#EA4335",
      fg: "#EA4335",
      svg: function () {
        // 흰 봉투 + 빨강 M valley (Gmail 공식 멀티컬러 근사)
        return '<svg viewBox="0 0 100 100" style="width:100%;height:100%">' +
          '<rect x="18" y="30" width="64" height="40" rx="6" fill="#FFFFFF" ' +
          'stroke="#E0E0E0" stroke-width="1"/>' +
          // left side (blue)
          '<path fill="#4285F4" d="M 18 36 L 18 70 L 28 70 L 28 44 Z"/>' +
          // right side (green)
          '<path fill="#34A853" d="M 82 36 L 82 70 L 72 70 L 72 44 Z"/>' +
          // left diagonal (red)
          '<path fill="#EA4335" d="M 18 36 L 28 36 L 50 53 L 50 65 Z"/>' +
          // right diagonal (yellow)
          '<path fill="#FBBC04" d="M 82 36 L 72 36 L 50 53 L 50 65 Z"/>' +
          '</svg>';
      },
    },
  };

  // 별칭(같은 브랜드 다른 key) → canonical key 매핑
  var ALIASES = {
    openai: "chatgpt",
    "open-ai": "chatgpt",
    gpt: "chatgpt",
    anthropic: "claude",
    yt: "youtube",
    google_mail: "gmail",
    googlemail: "gmail",
  };

  /**
   * 브랜드 key로 레지스트리 entry 조회. 미등록이면 null (소비 템플릿이 이니셜 폴백).
   * @param {string} key  brand key (대소문자/공백/하이픈 무시)
   * @returns {object|null}
   */
  function get(key) {
    if (!key || typeof key !== "string") return null;
    var norm = key.trim().toLowerCase().replace(/[\s_-]+/g, "");
    // 정규화된 key 로 alias/registry 동시 조회
    var aliasNorm = {};
    for (var a in ALIASES) {
      if (Object.prototype.hasOwnProperty.call(ALIASES, a)) {
        aliasNorm[a.replace(/[\s_-]+/g, "")] = ALIASES[a];
      }
    }
    if (Object.prototype.hasOwnProperty.call(aliasNorm, norm)) {
      norm = aliasNorm[norm];
    }
    if (Object.prototype.hasOwnProperty.call(REGISTRY, norm)) {
      return REGISTRY[norm];
    }
    return null;
  }

  /**
   * brand entry 의 완전한 <svg> 문자열 반환. fg 미지정 시 entry.fg 사용.
   * @param {string} key
   * @param {string=} fg  path fill override
   * @returns {string|null}
   */
  function svg(key, fg) {
    var e = get(key);
    if (!e || typeof e.svg !== "function") return null;
    return e.svg(fg);
  }

  window.BRAND_LOGOS = REGISTRY;
  // 헬퍼는 별도 네임스페이스로 노출(레지스트리 객체 오염 방지)
  window.BRAND_LOGOS_GET = get;
  window.BRAND_LOGOS_SVG = svg;
})();
