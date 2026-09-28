<script setup>
// Every setting of an emulator (Eden: qt-config.ini, RetroArch: retroarch.cfg + core options),
// grouped in tabs, with a draft of pending changes. First tab: Wolfy's own settings.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { act, api, toast } from '../api'
import HomeCombo from './HomeCombo.vue'
import SettingField from './SettingField.vue'
import WolfyEden from './WolfyEden.vue'

const props = defineProps({ emulator: { type: String, required: true } })
const NAMES = { eden: 'Eden', retroarch: 'RetroArch' }
const name = NAMES[props.emulator] || props.emulator
const base = `/emulator-settings/${props.emulator}`
const open = ref({}) // collapsed/expanded groups
const BIG = 40       // groups longer than this start collapsed

const data = ref(null)
const error = ref('')
const tab = ref('wolfy')
const search = ref('')
const draft = ref({}) // "section\0key" -> { value } | { reset: true }

const id = it => `${it.section}\u0000${it.key}`

async function load() {
  try {
    data.value = await api.get(base)
    draft.value = {}
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

const counts = computed(() => {
  const c = {}
  for (const it of data.value?.items || []) c[it.tab] = (c[it.tab] || 0) + 1
  return c
})

const visible = computed(() => {
  if (!data.value) return []
  const q = search.value.trim().toLowerCase()
  return data.value.items.filter(it => q
    ? `${it.label} ${it.key} ${it.help || ''} ${it.section}`.toLowerCase().includes(q)
    : it.tab === tab.value)
})

// groups inside a tab: Eden category, or player/shortcut name
const groups = computed(() => {
  const out = []
  const byName = {}
  for (const it of visible.value) {
    const name = search.value ? (tabLabel(it.tab)) : (it.group || it.category_label || `[${it.section}]`)
    if (!byName[name]) { byName[name] = { name, items: [] }; out.push(byName[name]) }
    byName[name].items.push(it)
  }
  return out
})

const tabLabel = t => data.value?.tabs.find(x => x.id === t)?.label || t

function valueOf(it) {
  const d = draft.value[id(it)]
  if (!d) return it.value
  return d.reset ? it.default : d.value
}

function update(it, v) {
  const d = { ...draft.value }
  if (v === it.value) delete d[id(it)]
  else d[id(it)] = it.type === 'raw' ? { raw: v, value: v } : { value: v }
  draft.value = d
}

function reset(it) {
  draft.value = { ...draft.value, [id(it)]: { reset: true } }
}

const pending = computed(() => Object.keys(draft.value).length)

async function save() {
  const changes = Object.entries(draft.value).map(([k, d]) => {
    const [section, key] = k.split('\u0000')
    return d.reset ? { section, key, reset: true } : d.raw !== undefined ? { section, key, raw: d.raw } : { section, key, value: d.value }
  })
  const r = await act(`Enregistrement de la configuration ${name}`,
    () => api.put(base, { changes, mtime: data.value.mtime }))
  if (r) {
    toast(`${r.changed} réglage(s) enregistré(s) — actif à la prochaine session`)
    load()
  }
}

async function restore(backup) {
  if (!backup) return
  if (!confirm(`Restaurer ${backupLabel(backup)} ?`)) return
  await act('Restauration', () => api.post(`${base}/backups/${backup}/restore`), 'Configuration restaurée')
  load()
}

const backupLabel = b => b.replace('qt-config.ini.', '').replace(/\.(\d{4}-)/, ' du $1').replace('_', ' ')
const isOpen = g => open.value[g.name] ?? (search.value || g.items.length <= BIG)
function toggle(g) { open.value = { ...open.value, [g.name]: !isOpen(g) } }

function beforeUnload(e) { if (pending.value) { e.preventDefault(); e.returnValue = '' } }
onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
defineExpose({ pending })
</script>

<template>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <template v-if="data">
    <div class="alert info small" style="margin-bottom:16px">
      <template v-if="data.description">{{ data.description }}</template>
      <template v-else>
        Configuration Eden <b>partagée</b> : utilisée par Eden sur le PC et copiée au démarrage de
        <b>chaque session Wolf</b>. Les changements s'appliquent aux prochaines sessions.
      </template>
      <code>{{ data.path }}</code> · réglages et libellés issus de {{ data.version || `Eden ${data.eden_tag}` }}.
    </div>
    <div v-if="data.host_running" class="alert warn small" style="margin-bottom:16px">
      {{ name }} est ouvert sur le PC : ferme-le avant d'enregistrer (il réécrit sa config en quittant).
    </div>

    <div class="row" style="margin-bottom:14px">
      <input v-model="search" placeholder="🔍 Rechercher un réglage (résolution, vsync, langue…)" style="flex:1;min-width:220px" />
      <select style="width:auto" @change="restore($event.target.value); $event.target.value = ''">
        <option value="">↺ Restaurer une sauvegarde…</option>
        <option v-for="b in data.backups" :key="b.name" :value="b.name">{{ backupLabel(b.name) }}</option>
      </select>
    </div>

    <div v-if="!search" class="tabs">
      <button type="button" :class="{ active: tab === 'wolfy' }" @click="tab = 'wolfy'">🐺 Wolfy-{{ name }}</button>
      <button v-for="t in data.tabs" :key="t.id" type="button" :class="{ active: tab === t.id }" @click="tab = t.id">
        {{ t.label }} <span class="muted small">{{ counts[t.id] || 0 }}</span>
      </button>
    </div>
    <div v-else class="muted small" style="margin-bottom:10px">{{ visible.length }} résultat(s)</div>

    <div v-if="tab === 'raw' && !search" class="alert warn small" style="margin-bottom:12px">
      Valeurs brutes du fichier (liaisons de boutons, listes, chemins…) : modifie seulement si tu sais ce que tu fais.
    </div>

    <template v-if="tab === 'wolfy' && !search">
      <WolfyEden v-if="emulator === 'eden'" />
      <HomeCombo v-else :emulator="emulator" />
    </template>

    <div v-for="g in groups" :key="g.name" class="card" style="padding:8px 4px;margin-bottom:14px">
      <h3 class="group-title" @click="toggle(g)">
        {{ isOpen(g) ? '▾' : '▸' }} {{ g.name }} <span class="muted small">{{ g.items.length }}</span>
      </h3>
      <template v-if="isOpen(g)">
        <SettingField v-for="it in g.items" :key="id(it)" :item="it" :value="valueOf(it)"
                      :modified="!!draft[id(it)]" @update="v => update(it, v)" @reset="reset(it)" />
      </template>
    </div>
    <div v-if="!groups.length && (tab !== 'wolfy' || search)" class="empty card">Aucun réglage.</div>

    <div v-if="pending" class="savebar">
      <span><b>{{ pending }}</b> modification(s) non enregistrée(s)</span>
      <div class="row">
        <button type="button" class="ghost" @click="draft = {}">Annuler</button>
        <button type="button" class="primary" @click="save">💾 Enregistrer</button>
      </div>
    </div>
  </template>
  <div v-else-if="!error" class="empty"><div class="spinner" style="margin:auto"></div></div>
</template>

<style scoped>
.group-title { padding: 8px 14px 4px; color: var(--accent-2); cursor: pointer; user-select: none; }
.savebar {
  position: sticky; bottom: 16px; z-index: 20;
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--card-2); border: 1px solid var(--accent); border-radius: 12px;
  padding: 12px 16px; box-shadow: var(--shadow);
}
</style>
