<script setup>
// "Wolfy-Eglantine" tab (app Switch): settings specific to Switch streaming through Wolf.
import { computed, onMounted, ref } from 'vue'
import { act, api } from '../api'
import HomeCombo from './HomeCombo.vue'
import SwitchPaths from './SwitchPaths.vue'

const data = ref(null)
const paths = ref(false)
const menuRes = ref(null) // null = follow the global resolution

const label = v => data.value?.resolution_options.find(o => o.value === v)?.label ?? v
const dirty = computed(() => data.value && menuRes.value !== data.value.menu_resolution)

async function load() {
  data.value = await api.get('/emulator-settings/switch/wolfy')
  menuRes.value = data.value.menu_resolution
}

async function saveRes() {
  const r = await act('Enregistrement', () => api.put('/emulator-settings/switch/wolfy/menu-resolution', { value: menuRes.value }),
    'Résolution du menu enregistrée — active à la prochaine session')
  if (r) { data.value = r; menuRes.value = r.menu_resolution }
}

async function savePads(auto) {
  const r = await act('Enregistrement', () => api.put('/emulator-settings/switch/wolfy/pads', { auto }),
    auto ? 'Détection automatique activée — appliquée au prochain lancement de jeu' : 'Détection automatique désactivée')
  if (r) data.value = r
}

onMounted(load)
</script>

<template>
  <div class="card">
    <p style="margin-top:0">Appli <b>Switch</b> : menu HOME de la console, jeux Switch 1 et 2. Chaque jeu tourne dans
      son propre processus Eglantine, avec la bonne horloge ; HOME le met en pause, le menu le reprend ou le ferme.</p>
    <p class="muted small" style="margin-bottom:0">Réglés par Wolfy à chaque démarrage de session : plein écran,
      fermeture sans confirmation, mémoire 12 Gio (le menu ne demande « Qui joue ? » que dans ce mode), sortie audio
      SDL2 et interface réseau du conteneur. Données : <code>config/switch</code>.</p>
    <button type="button" class="primary" style="margin-top:12px" @click="paths = true">
      <Icon name="sliders" />Clés, firmware, jeux</button>
  </div>
  <SwitchPaths v-if="paths" @close="paths = false" />

  <HomeCombo emulator="switch" />

  <div v-if="data" class="card" style="margin-bottom:18px">
    <div class="row between">
      <div>
        <h2 style="margin:0">Manettes : détection automatique</h2>
        <div class="muted small">Joueurs 1 à 4 = les manettes de la session, dans leur ordre de connexion.</div>
      </div>
      <label class="switch" title="Activer"><input :checked="data.pads_auto" type="checkbox" @change="savePads($event.target.checked)" /><span></span></label>
    </div>
    <div class="muted small" style="margin-top:10px">
      Avant le menu et chaque jeu, Wolfy relève les manettes branchées (Xbox, PlayStation, Switch… telles que
      Eglantine les voit) et en fait des manettes Pro : joueur 1 = première manette, jusqu'à 4. Les joueurs sans
      manette sont débranchés, le jeu voit exactement les manettes en main ; gyroscope repris quand la manette en a.
      Une manette ajoutée en cours de partie compte au lancement suivant ; débranchée puis rebranchée, elle
      retrouve sa place. Désactivé : les joueurs gardent les réglages de l'onglet Manettes.
    </div>
  </div>

  <div v-if="data" class="card">
    <h2 style="margin:0">Netteté du menu HOME</h2>
    <div class="muted small" style="margin-bottom:14px">
      Le menu HOME de la Switch est dessiné en 720p, même en mode dock : à la résolution globale 1X il est
      étiré sur le flux 1080p et paraît pixelisé. Ce réglage ne concerne que le menu, pas les jeux.
    </div>
    <div class="choices" role="radiogroup">
      <button type="button" class="choice" role="radio" :aria-checked="menuRes === null" :class="{ active: menuRes === null }" @click="menuRes = null">
        <span class="t">Comme les jeux</span>
        <span class="s">global : {{ label(data.global_resolution) }}</span>
      </button>
      <button v-for="o in data.resolution_options.filter(o => o.value >= 3 && o.value <= 8)" :key="o.value" type="button"
              class="choice" role="radio" :aria-checked="menuRes === o.value" :class="{ active: menuRes === o.value }" @click="menuRes = o.value">
        <span class="t">{{ o.label.split(' ')[0] }}<span v-if="o.value === 5" class="badge ok">Recommandé</span></span>
        <span class="s">
          menu en {{ { 3: '720p', 4: '900p', 5: '1080p', 6: '1440p', 7: '2160p (4K)', 8: '2880p' }[o.value] }}
        </span>
      </button>
    </div>
    <div class="muted small" style="margin-top:10px">
      1.5X donne exactement 1080p, la résolution du flux. Au-delà, l'image est calculée plus grande puis réduite
      (un peu plus fin, plus de charge GPU).
    </div>
    <div v-if="dirty" class="row end" style="margin-top:12px">
      <button type="button" class="ghost" @click="menuRes = data.menu_resolution">Annuler</button>
      <button type="button" class="primary" @click="saveRes"><Icon name="save" />Enregistrer</button>
    </div>
  </div>
</template>

<style scoped>
</style>
