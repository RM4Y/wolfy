<script setup>
// Browse the host's folders (read-only) and pick one.
import { onMounted, ref } from 'vue'
import { api } from '../api'

const props = defineProps({ start: String })
const emit = defineEmits(['pick', 'close'])
const listing = ref(null)
const error = ref('')

async function open(path) {
  try {
    listing.value = await api.get(`/fs?path=${encodeURIComponent(path || '/')}`)
    error.value = ''
  } catch (e) {
    error.value = e.message
    if (!listing.value && path !== '/') open('/')
  }
}

const join = (base, name) => (base === '/' ? `/${name}` : `${base}/${name}`)

onMounted(() => open(props.start || '/mnt'))
</script>

<template>
  <div class="modal-back" style="z-index:60" @click.self="emit('close')">
    <div class="modal narrow">
      <h2>Choisir un dossier</h2>
      <div v-if="listing" class="row" style="flex-wrap:nowrap;margin-bottom:10px">
        <button type="button" class="sm" :disabled="!listing.parent" @click="open(listing.parent)">⬆</button>
        <input class="mono small" :value="listing.path" @change="open($event.target.value)" />
      </div>
      <div v-if="error" class="alert bad small" style="margin-bottom:10px">{{ error }}</div>
      <div v-if="listing" class="list">
        <button v-for="d in listing.dirs" :key="d" type="button" class="ghost item" @click="open(join(listing.path, d))">
          📁 {{ d }}
        </button>
        <div v-if="!listing.dirs.length" class="muted small" style="padding:10px">Aucun sous-dossier</div>
      </div>
      <div class="row end" style="margin-top:12px">
        <button type="button" class="ghost" @click="emit('close')">Annuler</button>
        <button type="button" class="primary" :disabled="!listing" @click="emit('pick', listing.path)">Choisir ce dossier</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.list { max-height: 50vh; overflow: auto; border: 1px solid var(--line); border-radius: 10px; padding: 4px; }
.item { width: 100%; justify-content: flex-start; padding: 6px 10px; }
</style>
