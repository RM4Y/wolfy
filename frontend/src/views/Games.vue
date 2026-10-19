<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { act, ago, api, ApiError, bytes, isAdmin, toast } from '../api'

const data = ref(null)  // { platforms, wanted, queue }
const error = ref('')
const unconfigured = ref(false)
const tab = ref('catalog')
const game = ref('')
const result = ref(null)  // last request: { ok, release, seeders, error, game }
let timer

const platformName = slug => data.value?.platforms.find(p => p.slug === slug)?.name || slug

async function load() {
  clearTimeout(timer)
  try {
    data.value = await api.get('/games')
    error.value = ''
    unconfigured.value = false
  } catch (e) {
    unconfigured.value = e instanceof ApiError && e.status === 409
    error.value = unconfigured.value ? '' : e.message
  }
  // downloads move on their own: keep the lists fresh while the page is open
  if (!unconfigured.value) timer = setTimeout(load, 10000)
}

async function request(name, slug) {
  const r = await act(`Recherche de ${name}`, () => api.post('/games/request', { game: name, platform: slug }))
  if (!r) return
  result.value = { ...r, game: name }
  if (r.ok) toast(`${name} : téléchargement lancé`)
  else toast(`${name} ajouté aux demandes, Romarr réessaiera`, 'error')
  load()
}

async function submit() {
  if (!game.value.trim() || !platform.value) return
  await request(game.value.trim(), platform.value)
  if (result.value?.ok) game.value = ''
}

// ------------------------------------------------------------ catalogue (IGDB)
const saved = (() => { try { return localStorage.getItem('wolfy-games-platform') } catch { return null } })()
const platform = ref(saved || 'switch')
const catQ = ref('')
const catSort = ref('popular')
const cat = ref(null)  // { items, more, next, error, unconfigured }
const catBusy = ref(false)
let catTimer, catSeq = 0

async function loadCatalog(more = false) {
  if (!platform.value) return
  const seq = ++catSeq
  const offset = more ? cat.value.next : 0
  catBusy.value = true
  if (!more) cat.value = null
  try {
    const r = await api.get(`/games/catalog?platform=${encodeURIComponent(platform.value)}&q=${encodeURIComponent(catQ.value.trim())}`
      + `&sort=${catSort.value}&offset=${offset}`)
    if (seq !== catSeq) return
    // a game found by its other name on the first page can come back in IGDB's own search later
    const shown = new Set(more ? cat.value.items.map(g => g.id) : [])
    cat.value = more ? { ...r, items: [...cat.value.items, ...r.items.filter(g => !shown.has(g.id))] } : r
  } catch (e) {
    if (seq !== catSeq) return
    cat.value = { items: more ? cat.value.items : [], error: e.message, unconfigured: e instanceof ApiError && e.status === 409 }
  } finally {
    if (seq === catSeq) catBusy.value = false
  }
}
watch([platform, catSort], () => {
  try { localStorage.setItem('wolfy-games-platform', platform.value) } catch { /* private window */ }
  loadCatalog()
})
watch(catQ, () => { clearTimeout(catTimer); catTimer = setTimeout(loadCatalog, 400) })

// "Super Mario Galaxy 2" ~ "super mario galaxy 2!"
const norm = t => String(t).toLowerCase().normalize('NFD').replace(/[^a-z0-9]/g, '')
// where a catalogue game stands in Romarr: [label, badge class]
function status(g) {
  const n = norm(g.title)
  const q = data.value.queue.filter(i => i.platform === platform.value && norm(i.game) === n).pop()
  if (q && q.state !== 'failed') return STATES[q.state]
  if (data.value.wanted.some(w => w.platform === platform.value && norm(w.game) === n)) return ['Demandé', 'warn']
  return null
}

async function drop(w) {
  if (!confirm(`Retirer ${w.game} des demandes ?`)) return
  await act('Suppression', () => api.del(`/games/wanted?game=${encodeURIComponent(w.game)}&platform=${encodeURIComponent(w.platform)}`),
    'Demande retirée')
  load()
}

const STATES = { queued: ['En attente', 'warn'], grabbed: ['Téléchargement', 'accent'], imported: ['Importé', 'ok'], failed: ['Échec', 'bad'] }
const queue = computed(() => [...(data.value?.queue || [])].reverse())

// ------------------------------------------------------------ library
const lib = ref(null)
const libQ = ref('')
const libPlatform = ref('')
let libTimer

async function loadLibrary() {
  try {
    lib.value = await api.get(`/games/library?q=${encodeURIComponent(libQ.value)}&platform=${encodeURIComponent(libPlatform.value)}`)
    // Romarr reads its library in the background after a start, Wolfy finds the covers on IGDB
    if ((lib.value.loading || lib.value.identifying) && !lib.value.error) libTimer = setTimeout(loadLibrary, 3000)
  } catch (e) {
    lib.value = { items: [], error: e.message }
  }
}
watch([libQ, libPlatform], () => { clearTimeout(libTimer); libTimer = setTimeout(loadLibrary, 300) })

// ------------------------------------------------------------ discover
const shelf = ref('popular')
const disc = ref(null)
const picks = ref({})  // title -> chosen platform slug

async function loadDiscover() {
  disc.value = null
  try {
    disc.value = await api.get(`/games/discover?shelf=${shelf.value}`)
  } catch (e) {
    disc.value = { items: [], error: e.message }
  }
}
watch(shelf, loadDiscover)

// the catalogue's platforms that Romarr can download for
function requestable(g) {
  const known = data.value?.platforms || []
  return (g.platforms || []).map(p => known.find(k => k.name.toLowerCase() === String(p).toLowerCase() || k.slug === String(p).toLowerCase()))
    .filter((p, i, all) => p && all.indexOf(p) === i)
}

watch(tab, t => {
  if (t === 'library' && !lib.value) loadLibrary()
  if (t === 'discover' && !disc.value) loadDiscover()
})

onMounted(() => { load(); loadCatalog() })
onUnmounted(() => { clearTimeout(timer); clearTimeout(libTimer); clearTimeout(catTimer) })
</script>

<template>
  <div class="page-head">
    <h1>Mes jeux</h1>
    <div class="spacer"></div>
    <button v-if="data" class="ghost" @click="load"><Icon name="refresh" />Actualiser</button>
  </div>
  <div v-if="error" class="alert bad" style="margin-bottom:16px"><Icon name="alert" /><div>{{ error }}</div></div>

  <div v-if="unconfigured" class="card empty">
    <div class="icon"><Icon name="link" /></div>
    <div class="title">Romarr n'est pas configuré</div>
    <div class="text">Renseigne l'adresse et la clé API de Romarr pour demander des jeux depuis Wolfy.</div>
    <router-link v-if="isAdmin()" to="/parametres" class="btn primary" style="margin-top:8px"><Icon name="sliders" />Paramètres</router-link>
  </div>

  <template v-else-if="data">
    <div class="tabs">
      <button type="button" :class="{ active: tab === 'catalog' }" @click="tab = 'catalog'">Catalogue</button>
      <button type="button" :class="{ active: tab === 'wanted' }" @click="tab = 'wanted'">Demandés <span class="n">{{ data.wanted.length }}</span></button>
      <button type="button" :class="{ active: tab === 'queue' }" @click="tab = 'queue'">Téléchargements <span class="n">{{ data.queue.length }}</span></button>
      <button type="button" :class="{ active: tab === 'library' }" @click="tab = 'library'">Bibliothèque</button>
      <button type="button" :class="{ active: tab === 'discover' }" @click="tab = 'discover'">Découvrir</button>
    </div>

    <template v-if="tab === 'catalog'">
      <div class="row" style="gap:8px;margin-bottom:16px">
        <select v-model="platform" style="flex:1;min-width:160px;width:auto">
          <option v-for="p in data.platforms" :key="p.slug" :value="p.slug">{{ p.name }}</option>
        </select>
        <div class="search" style="flex:2;min-width:200px">
          <Icon name="search" class="ico" />
          <input v-model="catQ" placeholder="Chercher un jeu" maxlength="200" />
        </div>
        <select v-if="!catQ.trim()" v-model="catSort" style="width:auto">
          <option value="popular">Les plus connus</option>
          <option value="name">De A à Z</option>
        </select>
      </div>
      <div v-if="result" class="alert small" :class="result.ok ? 'info' : 'warn'" style="margin-bottom:16px">
        <template v-if="result.ok">
          <b>{{ result.game }}</b> : {{ result.release }}<span v-if="result.seeders"> · {{ result.seeders }} sources</span>
        </template>
        <template v-else>
          <b>{{ result.game }}</b> : rien de téléchargeable pour l'instant ({{ result.error || 'aucune version utilisable' }}).
          Le jeu reste dans les demandes, Romarr le recherche à nouveau régulièrement.
        </template>
      </div>
      <template v-if="cat?.unconfigured">
        <div class="alert warn" style="margin-bottom:16px"><Icon name="alert" />
          <div>Le catalogue et les jaquettes viennent d'IGDB : renseigne ses identifiants dans
            <router-link to="/parametres">Paramètres › IGDB</router-link>. En attendant, demande un jeu par son nom :</div>
        </div>
        <div class="card">
          <form class="row" style="gap:8px" @submit.prevent="submit">
            <div class="search" style="flex:2;min-width:200px">
              <Icon name="search" class="ico" />
              <input v-model="game" placeholder="Nom du jeu (ex. Super Metroid)" maxlength="200" />
            </div>
            <button type="submit" class="primary" :disabled="!game.trim() || !platform"><Icon name="download" />Demander ({{ platformName(platform) }})</button>
          </form>
        </div>
      </template>
      <div v-else-if="!cat" class="empty"><div class="spinner"></div></div>
      <div v-else-if="cat.error && !cat.items.length" class="alert warn"><Icon name="alert" /><div>{{ cat.error }}</div></div>
      <div v-else-if="!cat.items.length" class="card empty">
        <div class="icon"><Icon name="search" /></div><div class="title">Aucun jeu trouvé</div>
      </div>
      <template v-else>
        <div class="games">
          <article v-for="g in cat.items" :key="g.id" class="card tile">
            <div class="art">
              <img v-if="g.cover" :src="g.cover" alt="" loading="lazy" @error="$event.target.remove()" />
              <Icon name="gamepad" />
            </div>
            <div class="tile-body">
              <div class="tile-name">{{ g.title }}</div>
              <div v-if="g.alias" class="small muted">{{ g.alias }}</div>
              <div class="small muted">{{ g.year || '' }}<span v-if="g.rating"> · ★ {{ g.rating }}</span></div>
              <span v-if="status(g)" class="badge" :class="status(g)[1]" style="align-self:flex-start">{{ status(g)[0] }}</span>
              <button v-else class="sm" @click="request(g.title, platform)"><Icon name="download" />Demander</button>
            </div>
          </article>
        </div>
        <div v-if="cat.more" style="margin-top:16px;text-align:center">
          <button :disabled="catBusy" @click="loadCatalog(true)"><Icon name="chevron-down" />{{ catBusy ? 'Chargement…' : 'Voir plus' }}</button>
        </div>
      </template>
    </template>

    <div v-else-if="tab === 'wanted'" class="card">
      <div v-if="!data.wanted.length" class="empty">
        <div class="icon"><Icon name="check" /></div><div class="title">Aucune demande en attente</div>
      </div>
      <div v-else class="table-wrap cards">
        <table>
          <thead><tr><th>Jeu</th><th>Console</th><th>Demandé</th><th>Dernier essai</th><th></th></tr></thead>
          <tbody>
            <tr v-for="w in data.wanted" :key="w.platform + w.game">
              <td><b>{{ w.game }}</b></td>
              <td>{{ platformName(w.platform) }}</td>
              <td class="small muted">{{ ago(w.added) }}</td>
              <td class="small muted">
                <template v-if="w.attempts">{{ w.attempts }} essai{{ w.attempts > 1 ? 's' : '' }}<span v-if="w.last_error"> · {{ w.last_error }}</span></template>
                <template v-else>—</template>
              </td>
              <td class="act">
                <button class="sm" @click="request(w.game, w.platform)"><Icon name="refresh" />Rechercher</button>
                <button class="ghost sm icon" aria-label="Retirer" title="Retirer" @click="drop(w)"><Icon name="trash" /></button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="tab === 'queue'" class="card">
      <div v-if="!queue.length" class="empty">
        <div class="icon"><Icon name="download" /></div><div class="title">Aucun téléchargement</div>
      </div>
      <div v-else class="table-wrap cards">
        <table>
          <thead><tr><th>Jeu</th><th>Console</th><th>Version</th><th>État</th><th>Depuis</th></tr></thead>
          <tbody>
            <tr v-for="q in queue" :key="q.at + q.game">
              <td><b>{{ q.game }}</b></td>
              <td>{{ platformName(q.platform) }}</td>
              <td class="small mono" style="word-break:break-all">{{ q.release || '—' }}<span v-if="q.size" class="muted"> · {{ bytes(q.size) }}</span></td>
              <td>
                <span class="badge" :class="(STATES[q.state] || [])[1]">{{ (STATES[q.state] || [q.state])[0] }}</span>
                <div v-if="q.detail" class="small muted" style="margin-top:4px">{{ q.detail }}</div>
              </td>
              <td class="small muted">{{ ago(q.at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <template v-else-if="tab === 'library'">
      <div class="row" style="gap:8px;margin-bottom:16px">
        <div class="search" style="flex:2;min-width:200px">
          <Icon name="search" class="ico" />
          <input v-model="libQ" placeholder="Chercher dans la bibliothèque" />
        </div>
        <select v-model="libPlatform" style="flex:1;min-width:160px;width:auto">
          <option value="">Toutes les consoles</option>
          <option v-for="p in data.platforms" :key="p.slug" :value="p.slug">{{ p.name }}</option>
        </select>
      </div>
      <div v-if="!lib" class="empty"><div class="spinner"></div></div>
      <div v-else-if="lib.error" class="alert warn"><Icon name="alert" /><div>{{ lib.error }}</div></div>
      <div v-else-if="lib.loading" class="empty"><div class="spinner"></div>{{ lib.message || 'Lecture de la bibliothèque…' }}</div>
      <div v-else-if="!lib.items.length" class="card empty">
        <div class="icon"><Icon name="library" /></div><div class="title">Aucun jeu</div>
      </div>
      <template v-else>
        <div class="games">
          <article v-for="g in lib.items" :key="g.id" class="card tile">
            <div class="art">
              <img v-if="g.cover" :src="g.cover" alt="" loading="lazy" @error="$event.target.remove()" />
              <Icon name="gamepad" />
            </div>
            <div class="tile-body">
              <div class="tile-name">{{ g.title }}</div>
              <div class="small muted">{{ platformName(g.platform) }}<span v-if="g.year"> · {{ g.year }}</span></div>
            </div>
          </article>
        </div>
        <div v-if="lib.identifying" class="muted small" style="margin-top:12px;text-align:center">
          Recherche des jaquettes sur IGDB…
        </div>
      </template>
    </template>

    <template v-else-if="tab === 'discover'">
      <div class="row" style="gap:8px;margin-bottom:16px">
        <select v-model="shelf" style="width:auto">
          <option value="popular">Populaires</option>
          <option value="new">Sorties récentes</option>
          <option value="upcoming">À venir</option>
        </select>
        <span v-if="disc?.provider_label" class="muted small">via {{ disc.provider_label }}</span>
      </div>
      <div v-if="!disc" class="empty"><div class="spinner"></div></div>
      <div v-else-if="disc.error && !disc.items.length" class="alert warn">
        <Icon name="alert" /><div>{{ disc.error }} (Romarr › Settings › Metadata)</div>
      </div>
      <div v-else class="games">
        <article v-for="g in disc.items" :key="g.title" class="card tile">
          <div class="art">
            <img v-if="g.cover_url" :src="g.cover_url" alt="" loading="lazy" @error="$event.target.remove()" />
            <Icon name="gamepad" />
          </div>
          <div class="tile-body">
            <div class="tile-name">{{ g.title }}</div>
            <div class="small muted">{{ g.released || '' }}<span v-if="g.rating"> · ★ {{ g.rating.toFixed(1) }}</span></div>
            <template v-if="requestable(g).length">
              <select v-if="requestable(g).length > 1" v-model="picks[g.title]" class="sm">
                <option :value="undefined" disabled>Console</option>
                <option v-for="p in requestable(g)" :key="p.slug" :value="p.slug">{{ p.name }}</option>
              </select>
              <button class="sm" :disabled="requestable(g).length > 1 && !picks[g.title]"
                      @click="request(g.title, requestable(g).length > 1 ? picks[g.title] : requestable(g)[0].slug)">
                <Icon name="download" />Demander<span v-if="requestable(g).length === 1"> ({{ requestable(g)[0].name }})</span>
              </button>
            </template>
            <div v-else class="small muted">Pas sur une console gérée par Romarr</div>
          </div>
        </article>
      </div>
    </template>
  </template>
  <div v-else-if="!error" class="empty"><div class="spinner"></div></div>
</template>

<style scoped>
.games { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: var(--space-4); }
.tile { padding: 0; overflow: hidden; display: flex; flex-direction: column; }
.art { position: relative; aspect-ratio: 3 / 4; background: var(--surface-raised); display: grid; place-items: center; color: var(--ink-faint); }
.art img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.tile-body { flex: 1; padding: var(--space-3); display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.tile-name { font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; }
.tile-body button { margin-top: auto; justify-content: center; }
select.sm { height: 32px; font-size: 13px; }
@media (max-width: 600px) { .games { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); } }
</style>
