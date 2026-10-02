<script setup>
import { computed, ref } from 'vue'
import { act, api, coverUrl, toast } from '../api'
import ListEditor from './ListEditor.vue'

const props = defineProps({
  app: Object,          // null = new app
  profileId: String,
  emulators: Array,
  baseCreateJson: String,
  sessions: Number,
})
const emit = defineEmits(['close', 'saved'])

const isNew = !props.app
const form = ref(props.app ? structuredClone({ ...props.app }) : fromPreset(props.emulators[0], ''))
const tab = ref('general')
const covers = ref([])
const coversDir = ref('')
api.get('/covers').then(r => { covers.value = r.covers; coversDir.value = r.dir })

function fromPreset(emu, title) {
  return {
    title,
    icon: emu.icon || '',
    emulator: emu.id,
    image: emu.image,
    rom_dir: emu.rom_dir,
    mounts: [...emu.mounts],
    env: [...emu.env],
    devices: [],
    ports: [],
    base_create_json: emu.base_create_json || props.baseCreateJson,
    start_virtual_compositor: true,
    runner_type: 'docker',
    runner_name: '',
    notes: '',
  }
}

const emu = computed(() => props.emulators.find(e => e.id === form.value.emulator))

function applyPreset(id) {
  const preset = props.emulators.find(e => e.id === id)
  const keepTitle = form.value.title || preset.systems[0] || ''
  if (isNew || confirm(`Remplacer image, montages et variables par ceux de ${preset.name} ?`)) {
    const next = fromPreset(preset, keepTitle)
    // keep a cover chosen by hand, else take the new preset's default cover
    const previous = props.emulators.find(e => e.id === form.value.emulator)
    if (form.value.icon && form.value.icon !== previous?.icon) next.icon = form.value.icon
    next.runner_name = form.value.runner_name
    next.notes = form.value.notes
    form.value = next
  } else {
    form.value.emulator = id
  }
}

const jsonError = computed(() => {
  try { JSON.parse(form.value.base_create_json || '{}'); return '' } catch (e) { return e.message }
})

async function uploadCover(ev) {
  const file = ev.target.files[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file, file.name)
  const r = await act('Envoi de la jaquette', () => api.post('/covers', fd), 'Jaquette ajoutée')
  if (r) {
    form.value.icon = r.path
    covers.value = [...new Set([...covers.value, r.name])].sort()
  }
}

function pickCover(name) {
  form.value.icon = `${coversDir.value}/${name}`
}

async function save() {
  if (jsonError.value) return toast('base_create_json invalide', 'error')
  if (props.sessions && !confirm(`Wolf va redémarrer : ${props.sessions} session(s) en cours seront coupées. Continuer ?`)) return
  const url = isNew
    ? `/profiles/${props.profileId}/apps`
    : `/profiles/${props.profileId}/apps/${props.app.index}`
  const r = await act('Enregistrement et redémarrage de Wolf',
    () => (isNew ? api.post(url, form.value) : api.put(url, form.value)),
    isNew ? 'Application ajoutée' : 'Application mise à jour')
  if (r) emit('saved')
}
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <form class="modal" @submit.prevent="save">
      <div class="row between" style="margin-bottom:14px">
        <h2 style="margin:0">{{ isNew ? 'Nouvelle application' : `Modifier « ${app.title} »` }}</h2>
        <button type="button" class="ghost sm" @click="emit('close')">✖</button>
      </div>

      <div class="tabs">
        <button type="button" :class="{ active: tab === 'general' }" @click="tab = 'general'">Général</button>
        <button type="button" :class="{ active: tab === 'volumes' }" @click="tab = 'volumes'">Montages & variables</button>
        <button type="button" :class="{ active: tab === 'advanced' }" @click="tab = 'advanced'">Avancé</button>
      </div>

      <div v-show="tab === 'general'">
        <div class="field">
          <label>Émulateur principal</label>
          <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px">
            <button v-for="e in emulators" :key="e.id" type="button"
                    :class="{ primary: form.emulator === e.id }" style="flex-direction:column;align-items:flex-start;gap:2px"
                    @click="applyPreset(e.id)">
              <b>{{ e.name }}</b>
              <span class="small" :style="{ opacity: .8 }">{{ e.systems.join(', ') || 'Image au choix' }}</span>
            </button>
          </div>
          <div v-if="emu" class="help">
            {{ emu.description }}
            <span v-if="emu.image && !emu.image_info.present" class="badge warn">image absente — voir Émulateurs</span>
            <span v-if="!emu.multi_session" class="badge warn">une session à la fois</span>
          </div>
        </div>

        <div class="grid cols-2" style="gap:0 16px">
          <div class="field">
            <label>Titre affiché dans Moonlight</label>
            <input v-model="form.title" required placeholder="ex. Switch" />
          </div>
          <div class="field">
            <label>Image Docker</label>
            <input v-model="form.image" class="mono" required />
          </div>
        </div>

        <div class="field">
          <label>Dossier des ROMs (monté en lecture seule, même chemin)</label>
          <input v-model="form.rom_dir" class="mono" placeholder="/mnt/…/ROMS/…" />
        </div>

        <div class="field">
          <label>Jaquette (PNG, ratio 3:4 conseillé)</label>
          <div class="row" style="align-items:flex-start;flex-wrap:nowrap">
            <div style="width:90px;flex:none">
              <img v-if="form.icon" :src="coverUrl(form.icon)" class="cover" alt="" />
              <div v-else class="cover placeholder">🎮</div>
            </div>
            <div style="flex:1">
              <div class="row" style="margin-bottom:8px">
                <button v-for="c in covers" :key="c" type="button" class="sm"
                        :class="{ primary: form.icon.endsWith('/' + c) }" @click="pickCover(c)">{{ c }}</button>
              </div>
              <div class="row">
                <label class="btn sm" style="margin:0;color:var(--text)">
                  ⬆ Envoyer un PNG
                  <input type="file" accept="image/png" hidden @change="uploadCover" />
                </label>
                <button v-if="emu?.icon && form.icon !== emu.icon" type="button" class="sm"
                        @click="form.icon = emu.icon">↺ Image par défaut</button>
                <button v-if="form.icon" type="button" class="ghost sm" @click="form.icon = ''">Retirer</button>
              </div>
              <input v-model="form.icon" class="mono small" style="margin-top:8px" placeholder="chemin ou URL" />
            </div>
          </div>
        </div>

        <div class="field">
          <label>Notes</label>
          <textarea v-model="form.notes" style="min-height:60px" placeholder="Mémo pour toi (non envoyé à Wolf)"></textarea>
        </div>
      </div>

      <div v-show="tab === 'volumes'">
        <div class="field">
          <label>Montages supplémentaires <span class="mono">hôte:conteneur:mode</span></label>
          <ListEditor v-model="form.mounts" placeholder="/home/…:/home/retro/…:rw" />
          <div class="help">Le dossier des ROMs (onglet Général) est ajouté automatiquement.</div>
        </div>
        <div class="field">
          <label>Variables d'environnement</label>
          <ListEditor v-model="form.env" placeholder="CLE=valeur" />
        </div>
      </div>

      <div v-show="tab === 'advanced'">
        <div class="grid cols-2" style="gap:0 16px">
          <div class="field">
            <label>Nom du runner (préfixe des conteneurs)</label>
            <input v-model="form.runner_name" class="mono" placeholder="auto : Wolf + titre" />
          </div>
          <div class="field" style="display:flex;align-items:end">
            <label class="check"><input v-model="form.start_virtual_compositor" type="checkbox" /> Compositeur virtuel (Gamescope/Sway)</label>
          </div>
        </div>
        <div class="field">
          <label>Périphériques</label>
          <ListEditor v-model="form.devices" placeholder="/dev/…" />
        </div>
        <div class="field">
          <label>Ports</label>
          <ListEditor v-model="form.ports" placeholder="8080:8080" />
        </div>
        <div class="field">
          <label>base_create_json (options Docker)</label>
          <textarea v-model="form.base_create_json" class="mono" style="min-height:180px"></textarea>
          <div v-if="jsonError" class="help" style="color:var(--danger)">JSON invalide : {{ jsonError }}</div>
        </div>
      </div>

      <div class="alert warn small" style="margin:6px 0 14px">
        Enregistrer arrête Wolf, modifie <code>config.toml</code> (sauvegarde automatique) puis le redémarre.
      </div>
      <div class="row end">
        <button type="button" class="ghost" @click="emit('close')">Annuler</button>
        <button class="primary" :disabled="!!jsonError">💾 Enregistrer</button>
      </div>
    </form>
  </div>
</template>
