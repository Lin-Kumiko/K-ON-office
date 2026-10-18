<template>
  <!-- Original vector artwork: an after-school light-music clubroom at dusk (no characters). -->
  <div class="scene" aria-hidden="true">
    <svg class="room" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id="as-wall" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#E6B9A6" />
          <stop offset="1" stop-color="#C98E86" />
        </linearGradient>
        <linearGradient id="as-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#8C7BC6" />
          <stop offset="0.55" stop-color="#F28CA0" />
          <stop offset="1" stop-color="#F7B58B" />
        </linearGradient>
        <radialGradient id="as-glow" cx="0.28" cy="0.42" r="0.6">
          <stop offset="0" stop-color="#FFD9A0" stop-opacity="0.55" />
          <stop offset="1" stop-color="#FFD9A0" stop-opacity="0" />
        </radialGradient>
        <linearGradient id="as-floor" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#9C6B43" />
          <stop offset="1" stop-color="#6E4429" />
        </linearGradient>
        <linearGradient id="as-burst" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#F0A23B" />
          <stop offset="0.6" stop-color="#C2412E" />
          <stop offset="1" stop-color="#6B1A1A" />
        </linearGradient>
      </defs>

      <!-- wall, light from the window -->
      <rect width="1440" height="900" fill="url(#as-wall)" />
      <rect width="1440" height="900" fill="url(#as-glow)" />

      <!-- window -->
      <g transform="translate(70 70)">
        <rect x="-14" y="-14" width="588" height="508" rx="6" fill="#F4E6DA" />
        <rect width="560" height="480" fill="url(#as-sky)" />
        <circle cx="300" cy="400" r="70" fill="#FFE2B0" opacity="0.9" />
        <!-- distant school roofs -->
        <path d="M0 410 L90 380 L170 400 L260 360 L340 395 L430 370 L560 400 L560 480 L0 480 Z" fill="#7A5A8E" opacity="0.55" />
        <path d="M0 440 L120 425 L240 445 L380 420 L560 440 L560 480 L0 480 Z" fill="#5E466F" opacity="0.6" />
        <!-- mullions -->
        <rect x="273" y="0" width="14" height="480" fill="#F4E6DA" />
        <rect x="0" y="233" width="560" height="14" fill="#F4E6DA" />
        <!-- sakura branch reaching into the frame -->
        <g class="branch">
          <path d="M-20 40 C90 70 150 60 230 120 C270 150 300 150 340 140" stroke="#5B3A2E" stroke-width="12" fill="none" stroke-linecap="round" />
          <path d="M150 75 C170 30 200 20 240 10" stroke="#5B3A2E" stroke-width="7" fill="none" stroke-linecap="round" />
          <path d="M230 120 C250 175 240 200 260 230" stroke="#5B3A2E" stroke-width="6" fill="none" stroke-linecap="round" />
          <g fill="#F9B9CB">
            <circle cx="60" cy="40" r="26" /><circle cx="105" cy="70" r="30" /><circle cx="160" cy="45" r="28" />
            <circle cx="215" cy="20" r="24" /><circle cx="245" cy="105" r="30" /><circle cx="300" cy="135" r="26" />
            <circle cx="255" cy="200" r="22" /><circle cx="340" cy="145" r="20" />
          </g>
          <g fill="#FDE1E9">
            <circle cx="80" cy="30" r="12" /><circle cx="130" cy="62" r="14" /><circle cx="180" cy="38" r="11" />
            <circle cx="262" cy="98" r="13" /><circle cx="310" cy="128" r="11" /><circle cx="248" cy="190" r="9" />
          </g>
        </g>
        <rect x="-14" y="466" width="588" height="22" rx="4" fill="#E8D3C2" />
      </g>

      <!-- the club turtle's tank on the windowsill -->
      <g transform="translate(470 456)">
        <rect x="18" y="20" width="84" height="60" rx="6" fill="#BFE3E6" opacity="0.75" stroke="#EAF7F8" stroke-width="3" />
        <rect x="18" y="58" width="84" height="22" rx="4" fill="#E5D3A8" />
        <ellipse cx="62" cy="58" rx="16" ry="9" fill="#5E8B5A" />
        <circle cx="80" cy="56" r="5" fill="#7FA873" />
      </g>

      <!-- floor -->
      <rect y="700" width="1440" height="200" fill="url(#as-floor)" />
      <g stroke="#5A3820" stroke-width="2" opacity="0.35">
        <line x1="0" y1="740" x2="1440" y2="740" /><line x1="0" y1="790" x2="1440" y2="790" />
        <line x1="0" y1="850" x2="1440" y2="850" />
      </g>

      <!-- drum kit -->
      <g transform="translate(110 600) scale(0.82)">
        <line x1="-20" y1="20" x2="-20" y2="190" stroke="#3B3B3B" stroke-width="5" />
        <ellipse cx="-20" cy="20" rx="62" ry="12" fill="#E8C46A" />
        <line x1="260" y1="-10" x2="250" y2="190" stroke="#3B3B3B" stroke-width="5" />
        <ellipse cx="262" cy="-10" rx="70" ry="13" fill="#E8C46A" transform="rotate(-8 262 -10)" />
        <circle cx="120" cy="155" r="88" fill="#F2C14E" />
        <circle cx="120" cy="155" r="72" fill="#FFF4D8" />
        <circle cx="120" cy="155" r="18" fill="#F2C14E" opacity="0.6" />
        <rect x="18" y="66" width="70" height="44" rx="8" fill="#F2C14E" />
        <ellipse cx="53" cy="66" rx="35" ry="9" fill="#FFF4D8" />
        <rect x="160" y="60" width="62" height="40" rx="8" fill="#F2C14E" />
        <ellipse cx="191" cy="60" rx="31" ry="8" fill="#FFF4D8" />
      </g>

      <!-- tea table -->
      <g transform="translate(330 642) scale(0.8)">
        <rect x="0" y="0" width="360" height="22" rx="6" fill="#C8925A" />
        <path d="M-6 22 L366 22 L352 60 L8 60 Z" fill="#F7EFE8" />
        <path d="M8 60 Q60 72 110 60 Q170 72 230 60 Q290 72 352 60" fill="none" stroke="#F28CA0" stroke-width="5" />
        <rect x="24" y="60" width="16" height="140" fill="#9B6638" />
        <rect x="320" y="60" width="16" height="140" fill="#9B6638" />
        <!-- teapot -->
        <g transform="translate(60 -70)">
          <ellipse cx="40" cy="45" rx="42" ry="34" fill="#FFFDF8" />
          <path d="M78 40 Q108 28 112 6" stroke="#FFFDF8" stroke-width="9" fill="none" stroke-linecap="round" />
          <path d="M-2 30 Q-26 40 -2 62" stroke="#FFFDF8" stroke-width="8" fill="none" />
          <ellipse cx="40" cy="14" rx="20" ry="6" fill="#F28CA0" />
          <circle cx="40" cy="8" r="6" fill="#F28CA0" />
          <path d="M14 50 Q40 62 66 50" stroke="#F28CA0" stroke-width="4" fill="none" />
        </g>
        <!-- cups -->
        <g transform="translate(175 -30)">
          <ellipse cx="22" cy="30" rx="30" ry="6" fill="#FFFDF8" />
          <path d="M2 0 L42 0 L36 26 L8 26 Z" fill="#FFFDF8" />
          <path d="M42 6 Q56 10 40 20" stroke="#FFFDF8" stroke-width="5" fill="none" />
          <ellipse cx="22" cy="2" rx="20" ry="4" fill="#C1793A" />
        </g>
        <g transform="translate(240 -30)">
          <ellipse cx="22" cy="30" rx="30" ry="6" fill="#FFFDF8" />
          <path d="M2 0 L42 0 L36 26 L8 26 Z" fill="#FFFDF8" />
          <ellipse cx="22" cy="2" rx="20" ry="4" fill="#C1793A" />
        </g>
        <!-- strawberry shortcake on a stand -->
        <g transform="translate(300 -62)">
          <rect x="16" y="44" width="8" height="18" fill="#FFFDF8" />
          <ellipse cx="20" cy="62" rx="22" ry="5" fill="#FFFDF8" />
          <ellipse cx="20" cy="44" rx="34" ry="6" fill="#FFFDF8" />
          <path d="M0 40 L40 40 L40 18 L0 26 Z" fill="#FFF2DC" />
          <path d="M0 33 L40 30" stroke="#F28CA0" stroke-width="4" />
          <circle cx="24" cy="14" r="7" fill="#E23A4E" />
        </g>
        <!-- steam -->
        <g class="steam" stroke="#FFFFFF" stroke-width="3" fill="none" stroke-linecap="round" opacity="0.6">
          <path d="M190 -40 C180 -55 200 -65 190 -80" /><path d="M255 -40 C245 -55 265 -65 255 -80" />
        </g>
      </g>

      <!-- guitar on a stand -->
      <g transform="translate(640 520) rotate(-8)">
        <rect x="56" y="-150" width="18" height="190" rx="3" fill="#5B3A2E" />
        <rect x="52" y="-182" width="26" height="40" rx="6" fill="#2B2B2B" />
        <path d="M65 40 C20 40 0 80 8 120 C16 160 4 190 30 220 C60 250 110 248 128 214 C146 182 120 160 132 124 C142 92 118 40 65 40 Z" fill="url(#as-burst)" />
        <ellipse cx="66" cy="168" rx="26" ry="10" fill="#1E1E1E" />
        <rect x="40" y="118" width="52" height="10" rx="3" fill="#E8E2D6" />
        <rect x="40" y="140" width="52" height="10" rx="3" fill="#E8E2D6" />
      </g>
      <path d="M640 772 L690 660 L742 772" stroke="#2E2E2E" stroke-width="6" fill="none" />

      <!-- bass leaning on the wall -->
      <g transform="translate(770 470) rotate(10)">
        <rect x="58" y="-210" width="16" height="250" rx="3" fill="#4A2F25" />
        <rect x="54" y="-246" width="24" height="40" rx="6" fill="#1E1E1E" />
        <path d="M66 40 C24 36 8 80 18 118 C24 140 8 170 26 200 C50 236 112 236 128 196 C140 166 118 140 124 112 C132 74 112 42 66 40 Z" fill="#26262A" />
        <path d="M40 70 C70 60 96 72 104 104 L60 130 Z" fill="#F4F1E6" />
        <rect x="46" y="150" width="40" height="8" rx="3" fill="#B9B4A8" />
      </g>

      <!-- keyboard on an X stand -->
      <g transform="translate(1180 650)">
        <path d="M20 40 L200 150 M200 40 L20 150" stroke="#2E2E2E" stroke-width="7" />
        <rect x="-10" y="0" width="240" height="44" rx="8" fill="#3A3A3E" />
        <rect x="0" y="16" width="220" height="24" fill="#FAF8F2" />
        <g fill="#2B2B2B">
          <rect x="10" y="16" width="7" height="14" /><rect x="26" y="16" width="7" height="14" />
          <rect x="52" y="16" width="7" height="14" /><rect x="68" y="16" width="7" height="14" />
          <rect x="84" y="16" width="7" height="14" /><rect x="110" y="16" width="7" height="14" />
          <rect x="126" y="16" width="7" height="14" /><rect x="152" y="16" width="7" height="14" />
          <rect x="168" y="16" width="7" height="14" /><rect x="184" y="16" width="7" height="14" />
          <rect x="208" y="16" width="7" height="14" />
        </g>
      </g>
    </svg>

    <!-- a few petals drifting past the window: the only ambient motion on the page -->
    <span v-for="p in petals" :key="p.id" class="petal" :style="p.style" />
  </div>
</template>

<script setup lang="ts">
const petals = Array.from({ length: 9 }, (_, i) => ({
  id: i,
  style: {
    left: `${6 + ((i * 37) % 36)}%`,
    animationDelay: `${(i * 1.7) % 12}s`,
    animationDuration: `${11 + (i % 4) * 3}s`,
    transform: `scale(${0.7 + (i % 3) * 0.25})`,
  },
}))
</script>

<style scoped>
.scene {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: #c98e86;
}
.room {
  width: 100%;
  height: 100%;
  display: block;
}
.petal {
  position: absolute;
  top: -24px;
  width: 14px;
  height: 11px;
  background: #fbc8d6;
  border-radius: 12px 0 12px 0;
  opacity: 0.9;
  animation: drift linear infinite;
}
@keyframes drift {
  0% {
    translate: 0 0;
    rotate: 0deg;
    opacity: 0;
  }
  10% {
    opacity: 0.9;
  }
  100% {
    translate: 120px 78vh;
    rotate: 320deg;
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .petal {
    display: none;
  }
}
</style>
