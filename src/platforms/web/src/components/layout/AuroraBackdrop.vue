<template>
  <div class="ikaros-aurora" aria-hidden="true">
    <span class="ikaros-aurora__wing ikaros-aurora__wing--one" />
    <span class="ikaros-aurora__wing ikaros-aurora__wing--two" />
    <span class="ikaros-aurora__glow" />
    <span class="ikaros-aurora__orbit ikaros-aurora__orbit--one" />
    <span class="ikaros-aurora__orbit ikaros-aurora__orbit--two" />
    <span class="ikaros-aurora__rind" />
  </div>
</template>

<style scoped>
.ikaros-aurora {
  position: absolute;
  z-index: 0;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.ikaros-aurora::before {
  position: absolute;
  inset: 0;
  background-color: var(--ikaros-glass-behind, #f1eef2);
  background-image: var(--ikaros-glass-wallpaper-image);
  background-position: var(--ikaros-glass-wallpaper-position, center);
  background-repeat: var(--ikaros-glass-wallpaper-repeat, no-repeat);
  background-size: var(--ikaros-glass-wallpaper-size, cover);
  content: '';
}

.ikaros-aurora::after {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(232, 93, 142, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(42, 140, 138, 0.04) 1px, transparent 1px);
  background-size: 46px 46px;
  content: '';
  mask-image: radial-gradient(ellipse at 62% 46%, #000 0%, rgba(0, 0, 0, 0.72) 48%, transparent 86%);
  opacity: 0.56;
}

.ikaros-aurora__wing,
.ikaros-aurora__glow {
  position: absolute;
  border-radius: 999px;
  filter: blur(64px);
  will-change: transform;
}

.ikaros-aurora__wing {
  width: 62vw;
  height: 18vw;
  min-height: 180px;
  background: linear-gradient(90deg, transparent, rgba(232, 93, 142, 0.2), transparent);
}

.ikaros-aurora__wing--one {
  top: 5%;
  left: -18%;
  transform: rotate(-13deg);
}

.ikaros-aurora__wing--two {
  right: -18%;
  bottom: 8%;
  transform: rotate(21deg);
}

.ikaros-aurora__glow {
  top: 24%;
  right: 4%;
  width: 36vw;
  height: 36vw;
  background: radial-gradient(circle, rgba(42, 140, 138, 0.13), transparent 68%);
  filter: blur(76px);
}

.ikaros-aurora__orbit {
  position: absolute;
  border: 1px solid rgba(232, 93, 142, 0.13);
  border-radius: 50%;
  box-shadow: 0 0 38px rgba(232, 93, 142, 0.045);
}

.ikaros-aurora__orbit--one {
  top: 4%;
  right: 5%;
  width: min(36vw, 520px);
  height: min(36vw, 520px);
}

.ikaros-aurora__orbit--two {
  bottom: -14%;
  left: 18%;
  width: min(31vw, 440px);
  height: min(31vw, 440px);
  border-color: rgba(42, 140, 138, 0.11);
}

.ikaros-aurora__rind {
  position: absolute;
  top: 15%;
  left: 43%;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #2f7d4a;
  box-shadow: 0 0 18px rgba(47, 125, 74, 0.28);
  opacity: 0.42;
}

@media (prefers-reduced-motion: no-preference) {
  .ikaros-aurora__wing--one { animation: ikaros-wing-one 22s ease-in-out infinite alternate; }
  .ikaros-aurora__wing--two { animation: ikaros-wing-two 27s ease-in-out infinite alternate; }
  .ikaros-aurora__glow { animation: ikaros-eye-glow 30s ease-in-out infinite alternate; }
}

@keyframes ikaros-wing-one {
  to { transform: translate3d(58px, -24px, 0) rotate(-9deg) scale(1.08); }
}

@keyframes ikaros-wing-two {
  to { transform: translate3d(-44px, 34px, 0) rotate(17deg) scale(1.12); }
}

@keyframes ikaros-eye-glow {
  to { transform: translate3d(-64px, -24px, 0) scale(1.17); }
}

</style>
