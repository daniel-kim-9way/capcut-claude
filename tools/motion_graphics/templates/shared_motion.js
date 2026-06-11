/*
 * shared_motion.js — 공유 모션 헬퍼 (2026-06-11)
 * ----------------------------------------------------------------------------
 * 모든 GSAP 모션 템플릿이 공유하는 "연출 어휘". render_motion.py는 GSAP 타임라인을
 * paused 상태로 두고 progress(0~1)로 프레임을 스텝하므로, 벽시계 기반 CSS 애니메이션은
 * 프레임과 동기되지 않는다. 따라서 모든 헬퍼는 **타임라인(tl)에 유한 tween을 추가**하는
 * 형태여야 progress 매핑이 안전하다(무한 repeat:-1 금지 — duration이 Infinity가 됨).
 *
 * 사용: 템플릿 HTML에서 <script src="shared_motion.js"></script> 로드 후
 *       window.MGMotion.livingHold(...) / window.MGMotion.choreographedExit(...) 호출.
 */
(function () {
  const MGMotion = {
    /**
     * livingHold — hold 구간에 미세 drift+scale 오실레이션을 추가해 카드가 "안 얼게" 한다.
     *   카드가 등장 후 정적으로 멈춰 hard-cut 되던 "pop-and-freeze" 문제 해결.
     * @param {gsap.core.Timeline} tl  대상 타임라인
     * @param {Element|string}     el  대상 엘리먼트(또는 셀렉터)
     * @param {number} at   오실레이션 시작 초(보통 등장 완료 시점)
     * @param {number} dur  hold 길이 초
     * @param {{cycle?:number, ampY?:number, ampS?:number}} opts
     *        cycle=한 호흡 주기(기본 3.0s), ampY=세로 진폭 px(기본 4), ampS=scale 진폭(기본 0.010)
     */
    livingHold(tl, el, at, dur, opts) {
      opts = opts || {};
      const cycle = opts.cycle || 3.0;
      const ampY = opts.ampY == null ? 4 : opts.ampY;
      const ampS = opts.ampS == null ? 0.010 : opts.ampS;
      const half = cycle / 2;
      const reps = Math.max(1, Math.round(dur / half)); // 유한 yoyo half-cycle 반복
      tl.to(
        el,
        { y: "-=" + ampY, scale: "+=" + ampS, duration: half, ease: "sine.inOut", yoyo: true, repeat: reps - 1 },
        at
      );
      return tl;
    },

    /**
     * choreographedExit — 클립 끝에서 hard-cut 대신 dissolve-forward 퇴장.
     *   살짝 커지며(scale +0.04) 위로 떠오르고(y -14) blur+fade 되며 사라진다.
     * @param {gsap.core.Timeline} tl
     * @param {Element|string}     el
     * @param {number} at   퇴장 시작 초(보통 hold 끝 - dur)
     * @param {{dur?:number, ampS?:number, ampY?:number, blur?:number}} opts
     */
    choreographedExit(tl, el, at, opts) {
      opts = opts || {};
      const dur = opts.dur || 0.45;
      const ampS = opts.ampS == null ? 0.04 : opts.ampS;
      const ampY = opts.ampY == null ? 14 : opts.ampY;
      const blur = opts.blur == null ? 6 : opts.blur;
      tl.to(
        el,
        { opacity: 0, scale: "+=" + ampS, y: "-=" + ampY, filter: "blur(" + blur + "px)", duration: dur, ease: "power2.in" },
        at
      );
      return tl;
    },

    /**
     * livingTail — 흔한 패턴 헬퍼: 등장 완료(consumed)부터 전체 길이(D)까지를 hold로 보고
     *   livingHold + 마지막 exitDur 만큼 choreographedExit을 한 번에 건다. 반환은 tl.
     *   템플릿 끝부분 `tl.to({}, {duration: D - consumed})` (정적 tail) 대체용.
     */
    livingTail(tl, el, consumed, D, opts) {
      opts = opts || {};
      const exitDur = opts.exitDur == null ? 0.45 : opts.exitDur;
      const holdDur = Math.max(0.1, D - consumed - exitDur);
      if (holdDur > 0.3) this.livingHold(tl, el, consumed, holdDur, opts);
      this.choreographedExit(tl, el, Math.max(consumed, D - exitDur), opts);
      return tl;
    },
  };

  window.MGMotion = MGMotion;
})();
