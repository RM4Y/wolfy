<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { act, api } from '../api'
import Cover from '../components/Cover.vue'

const sessions = ref([])
const netAvailable = ref(true)
const apps = ref([])
const error = ref('')
const now = ref(Date.now() / 1000)
let timer, clock

async function load() {
  clearTimeout(timer)
  try {
    const r = await api.get('/sessions')
    sessions.value = r.sessions
    netAvailable.value = r.net_available
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
  timer = setTimeout(load, 2000)
}

async function loadApps() {
  try {
    apps.value = (await api.get('/profiles')).profiles.flatMap(p => p.apps)
  } catch { /* covers fall back to the title's initial */ }
}

const sid = s => String(s.session_id ?? s.client_id ?? s.id)
const appOf = s => apps.value.find(a => a.title === s.app_title) || { title: s.app_title || '?' }

// streaming: video flowing; background: Moonlight minimized (audio only); idle: nothing sent
function state(s) {
  if (!s.net) return netAvailable.value ? { id: 'idle', label: 'Inactif' } : { id: 'live', label: 'En cours' }
  if (s.net.video_bps > 100e3) return { id: 'live', label: 'En direct' }
  if (s.net.audio_bps > 10e3) return { id: 'background', label: 'En arrière-plan' }
  return { id: 'idle', label: 'Inactif' }
}

function rate(bps) {
  if (bps == null) return '—'
  if (bps < 1e6) return `${Math.round(bps / 1e3)} kbit/s`
  return `${(bps / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: bps < 10e6 ? 1 : 0 })} Mbit/s`
}

function stats(s) {
  const h = s.net?.history || []
  if (!h.length) return null
  const avg = h.reduce((a, b) => a + b, 0) / h.length
  return { avg, peak: Math.max(...h), perHour: avg * 3600 / 8 / 1e9 }
}

function duration(s) {
  const sec = Math.max(0, Math.round(now.value - s.started_at))
  if (sec < 60) return `${sec} s`
  const m = Math.floor(sec / 60)
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`
}

function countdown(at) {
  const sec = Math.max(0, Math.round(at - now.value))
  return sec >= 60 ? `${Math.ceil(sec / 60)} min` : `${sec} s`
}

function res(s) {
  return s.video_width ? `${s.video_width}×${s.video_height}${s.video_refresh_rate ? ` · ${s.video_refresh_rate} i/s` : ''}` : ''
}

// 60 s sparkline: line + area, newest point on the right
const W = 300, H = 72
function spark(s) {
  const h = s.net?.history || []
  if (h.length < 2) return null
  const max = Math.max(...h, 1e6) * 1.15
  const step = W / 59
  const x0 = W - (h.length - 1) * step
  const pts = h.map((v, i) => [x0 + i * step, H - 2 - (v / max) * (H - 6)])
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return { line, area: `${line} L${W},${H} L${x0.toFixed(1)},${H} Z`, end: pts[pts.length - 1] }
}

async function stop(s) {
  if (!confirm(`Arrêter la session « ${s.app_title || s.app_id} » de ${s.client_name || s.client_ip || 'cet appareil'} ?`)) return
  await act('Arrêt de la session', () => api.post('/sessions/stop', { session_id: sid(s) }), 'Session arrêtée')
  load()
}

onMounted(() => { load(); loadApps(); clock = setInterval(() => { now.value = Date.now() / 1000 }, 1000) })
onUnmounted(() => { clearTimeout(timer); clearInterval(clock) })
</script>

<template>
  <div class="page-head">
    <h1>Sessions</h1>
  </div>
  <div v-if="error" class="alert bad" style="margin-bottom:16px"><Icon name="alert" /><div>{{ error }}</div></div>

  <div v-if="sessions.length" class="sessions">
    <article v-for="s in sessions" :key="sid(s)" class="card session" :class="`is-${state(s).id}`">
      <div class="top">
        <div class="thumb-wrap">
          <Cover :app="appOf(s)" :label="false" class="thumb" />
          <span v-if="state(s).id === 'live'" class="ring"></span>
        </div>
        <div class="who">
          <div class="app">{{ s.app_title || s.app_id }}</div>
          <div class="muted">{{ s.client_name || 'Appareil inconnu' }} · <span class="mono">{{ s.client_ip }}</span></div>
          <div class="row" style="gap:6px;margin-top:8px">
            <span class="status" :class="state(s).id">
              <span class="eq" aria-hidden="true"><i></i><i></i><i></i><i></i></span>{{ state(s).label }}
            </span>
            <span class="badge">depuis {{ duration(s) }}</span>
            <span v-if="res(s)" class="badge">{{ res(s) }}</span>
            <span v-if="s.audio_channel_count" class="badge">{{ s.audio_channel_count }} canaux</span>
            <span v-if="s.idle_stop_at" class="badge warn" title="Fermeture automatique des sessions inactives (Paramètres)">
              Fermeture dans {{ countdown(s.idle_stop_at) }}
            </span>
          </div>
        </div>
        <button class="danger sm" @click="stop(s)"><Icon name="stop" />Arrêter</button>
      </div>

      <div v-if="s.net" class="bw">
        <div class="now">
          <span class="overline">Débit</span>
          <span class="value">{{ rate(s.net.video_bps + s.net.audio_bps) }}</span>
          <span class="split">
            <span><i class="key-v"></i>Vidéo {{ rate(s.net.video_bps) }}</span>
            <span><i class="key-a"></i>Audio {{ rate(s.net.audio_bps) }}</span>
          </span>
        </div>
        <div class="chart">
          <svg v-if="spark(s)" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient :id="`g${sid(s)}`" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="var(--brand)" stop-opacity=".45" />
                <stop offset="1" stop-color="var(--brand)" stop-opacity="0" />
              </linearGradient>
            </defs>
            <path :d="spark(s).area" :fill="`url(#g${sid(s)})`" />
            <path :d="spark(s).line" class="line" vector-effect="non-scaling-stroke" />
          </svg>
          <span v-if="spark(s)" class="head" :style="{ left: `${spark(s).end[0] / W * 100}%`, top: `calc(8px + (100% - 8px) * ${spark(s).end[1] / H})` }"></span>
          <span class="axis">60 s</span>
        </div>
        <div v-if="stats(s)" class="facts">
          <div><span class="overline">Moyenne</span><b>{{ rate(stats(s).avg) }}</b></div>
          <div><span class="overline">Pic</span><b>{{ rate(stats(s).peak) }}</b></div>
          <div><span class="overline">Volume</span><b>≈ {{ stats(s).perHour.toLocaleString('fr-FR', { maximumFractionDigits: 1 }) }} Go/h</b></div>
        </div>
      </div>
      <div v-else-if="netAvailable" class="muted small">Aucun paquet envoyé à cet appareil depuis une minute.</div>
    </article>
  </div>
  <div v-else-if="!error" class="card empty">
    <div class="icon"><Icon name="radio" /></div>
    <div class="title">Aucune session en cours</div>
    <div class="text">Lance une application depuis Moonlight pour la voir ici.</div>
  </div>

  <div v-if="!netAvailable" class="alert warn" style="margin-top:24px">
    <Icon name="alert" />
    <div>Débit indisponible : le service <code>wolfy-net</code> ne tourne pas (<code>docker compose up -d</code>).</div>
  </div>
  <div class="alert" style="margin-top:24px">
    <Icon name="info" />
    <div>Si une session plante, <strong>quitte-la dans Moonlight</strong> (« Quitter la session ») avant de la relancer :
      reprendre une session dont le conteneur est mort fait planter Wolf.</div>
  </div>
</template>

<style scoped>
.sessions { display: grid; gap: var(--space-6); }
.session + .session { margin-top: 0; }
.session { display: flex; flex-direction: column; gap: var(--space-5); transition: box-shadow .4s; }
.session.is-live { box-shadow: var(--shadow-card), 0 0 48px -18px var(--glow-brand); }
.top { display: flex; gap: var(--space-4); align-items: flex-start; }
.who { flex: 1; min-width: 0; }
.app { font: 650 20px/26px var(--font-display); letter-spacing: -.01em; }

.thumb-wrap { position: relative; flex: none; }
.thumb { width: 72px; aspect-ratio: 1; border-radius: var(--radius-lg); padding: 8px; }
.thumb :deep(.glyph) { font-size: 72px; top: -8px; }
.ring { position: absolute; inset: -4px; border-radius: calc(var(--radius-lg) + 4px); border: 2px solid var(--success); opacity: 0; animation: ring 2.4s ease-out infinite; pointer-events: none; }
@keyframes ring { 0% { opacity: .7; transform: scale(.96); } 100% { opacity: 0; transform: scale(1.12); } }

/* status pill with an equalizer: bars dance while live, rest otherwise */
.status { white-space: nowrap; display: inline-flex; align-items: center; gap: 8px; height: 24px; padding: 0 10px 0 8px; border-radius: var(--radius-pill); font: 600 12px/1 var(--font-sans); }
.status.live { color: var(--success); background: var(--success-soft); box-shadow: 0 0 18px -6px var(--success); }
.status.background { color: var(--warning); background: var(--warning-soft); }
.status.idle { color: var(--ink-muted); background: var(--surface-raised); border: 1px solid var(--border); }
.eq { display: inline-flex; align-items: flex-end; gap: 2px; height: 12px; }
.eq i { width: 3px; height: 30%; border-radius: 2px; background: currentColor; }
.status.live .eq i { animation: eq 1s ease-in-out infinite alternate; }
.status.live .eq i:nth-child(2) { animation-duration: .7s; animation-delay: -.3s; }
.status.live .eq i:nth-child(3) { animation-duration: 1.2s; animation-delay: -.6s; }
.status.live .eq i:nth-child(4) { animation-duration: .85s; animation-delay: -.2s; }
.status.background .eq i { height: 45%; animation: breathe 2.4s ease-in-out infinite; }
@keyframes eq { 0% { height: 20%; } 100% { height: 100%; } }
@keyframes breathe { 50% { opacity: .35; } }

.bw { display: grid; grid-template-columns: 200px minmax(0, 1fr) 170px; gap: var(--space-5); align-items: stretch;
  padding-top: var(--space-5); border-top: 1px solid var(--border); }
.now { display: flex; flex-direction: column; gap: 4px; }
.now .value { font: 650 28px/34px var(--font-display); letter-spacing: -.01em; font-variant-numeric: tabular-nums; text-shadow: 0 0 24px rgba(180,159,255,0.25); }
.split { display: flex; flex-direction: column; gap: 2px; font-size: 12.5px; color: var(--ink-muted); font-variant-numeric: tabular-nums; }
.split i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 6px; }
.key-v { background: var(--brand); }
.key-a { background: var(--platform-wii); }
.chart { position: relative; min-height: 88px; border-radius: var(--radius-md); background: var(--surface-sunken); overflow: hidden; }
.chart svg { position: absolute; inset: 8px 0 0; width: 100%; height: calc(100% - 8px); }
.chart .line { fill: none; stroke: var(--brand-text); stroke-width: 2; stroke-linejoin: round; filter: drop-shadow(0 0 6px var(--glow-brand)); }
.chart path { transition: d .9s linear; }
.head { position: absolute; width: 8px; height: 8px; margin: -4px 0 0 -4px; border-radius: 50%; background: var(--brand-text);
  box-shadow: 0 0 0 0 var(--glow-brand); animation: head 1.6s ease-out infinite; transition: top .9s linear; }
@keyframes head { 0% { box-shadow: 0 0 0 0 var(--glow-brand); } 100% { box-shadow: 0 0 0 10px transparent; } }
.axis { position: absolute; left: 8px; bottom: 6px; font-size: 11px; color: var(--ink-faint); }
.facts { display: flex; flex-direction: column; justify-content: center; gap: 8px; }
.facts > div { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.facts b { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }

@media (max-width: 899px) {
  .bw { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
  .top { display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: var(--space-3); }
  .thumb { width: 56px; }
  .thumb :deep(.glyph) { font-size: 56px; }
  .top > button { grid-column: 1 / -1; justify-self: end; }
  .app { font-size: 18px; line-height: 24px; }
}
@media (prefers-reduced-motion: reduce) {
  .ring, .head, .status .eq i { animation: none; }
}
</style>
