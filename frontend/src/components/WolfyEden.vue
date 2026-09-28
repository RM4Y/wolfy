<script setup>
// "Wolfy-Eden" tab: settings specific to Switch streaming through Wolf.
import { computed, onMounted, ref } from 'vue'
import { act, api } from '../api'
import HomeCombo from './HomeCombo.vue'

const data = ref(null)
const menuRes = ref(null) // null = follow the global resolution

const label = v => data.value?.resolution_options.find(o => o.value === v)?.label ?? v
const dirty = computed(() => data.value && menuRes.value !== data.value.menu_resolution)

async function load() {
  data.value = await api.get('/emulator-settings/eden/wolfy')
  menuRes.value = data.value.menu_resolution
}

async function saveRes() {
  const r = await act('Enregistrement', () => api.put('/emulator-settings/eden/wolfy/menu-resolution', { value: menuRes.value }),
    'Résolution du menu enregistrée — active à la prochaine session')
  if (r) { data.value = r; menuRes.value = r.menu_resolution }
}

onMounted(load)
</script>

<template>
  <HomeCombo />

  <div v-if="data" class="card">
    <h2 style="margin:0">✨ Netteté du menu HOME</h2>
    <div class="muted small" style="margin-bottom:14px">
      Le menu HOME de la Switch est dessiné en 720p, même en mode dock : à la résolution globale 1X il est
      étiré sur le flux 1080p et paraît pixelisé. Ce réglage ne concerne que le menu, pas les jeux.
    </div>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
      <button type="button" class="pick" :class="{ primary: menuRes === null }" @click="menuRes = null">
        <b>Comme les jeux</b>
        <span class="small">global : {{ label(data.global_resolution) }}</span>
      </button>
      <button v-for="o in data.resolution_options.filter(o => o.value >= 3 && o.value <= 8)" :key="o.value" type="button"
              class="pick" :class="{ primary: menuRes === o.value }" @click="menuRes = o.value">
        <b>{{ o.label.split(' ')[0] }}</b>
        <span class="small">
          menu en {{ { 3: '720p', 4: '900p', 5: '1080p', 6: '1440p', 7: '2160p (4K)', 8: '2880p' }[o.value] }}
          <template v-if="o.value === 5"> · recommandé</template>
        </span>
      </button>
    </div>
    <div class="muted small" style="margin-top:10px">
      1.5X donne exactement 1080p, la résolution du flux. Au-delà, l'image est calculée plus grande puis réduite
      (un peu plus fin, plus de charge GPU).
    </div>
    <div v-if="dirty" class="row end" style="margin-top:12px">
      <button type="button" class="ghost" @click="menuRes = data.menu_resolution">Annuler</button>
      <button type="button" class="primary" @click="saveRes">💾 Enregistrer</button>
    </div>
  </div>
</template>

<style scoped>
.pick { flex-direction: column; align-items: flex-start; gap: 0; }
</style>
