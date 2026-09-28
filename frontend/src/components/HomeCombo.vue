<script setup>
// Gamepad combo that brings a Switch session back to the HOME menu.
import { computed, onMounted, ref } from 'vue'
import { act, api } from '../api'

const saved = ref(null)
const form = ref(null)

const MODIFIERS = [
  { id: 'start', label: 'Start', hint: 'bouton ☰ (Menu)' },
  { id: 'guide', label: 'Guide', hint: 'bouton Xbox / Home au centre' },
]
// Xbox labels, as printed on the pad; Eden uses Nintendo positions
const BUTTONS = [
  { id: 'a', label: 'A', hint: 'en bas', color: '#3ecf8e' },
  { id: 'b', label: 'B', hint: 'à droite', color: '#ff5c7a' },
  { id: 'x', label: 'X', hint: 'à gauche', color: '#4ea3ff' },
  { id: 'y', label: 'Y', hint: 'en haut', color: '#f5b041' },
]

const dirty = computed(() => JSON.stringify(form.value) !== JSON.stringify(saved.value))
const modLabel = computed(() => MODIFIERS.find(m => m.id === form.value?.modifier)?.label)
const btnLabel = computed(() => BUTTONS.find(b => b.id === form.value?.button)?.label)

async function load() {
  saved.value = await api.get('/emulator-settings/eden/home-combo')
  form.value = { ...saved.value }
}

async function save() {
  const r = await act('Enregistrement', () => api.put('/emulator-settings/eden/home-combo', form.value),
    'Combinaison enregistrée — active dans les sessions en cours sous 2 s')
  if (r) { saved.value = r; form.value = { ...r } }
}

onMounted(load)
</script>

<template>
  <div v-if="form" class="card" style="margin-bottom:18px">
    <div class="row between">
      <div>
        <h2 style="margin:0">🏠 Retour au menu HOME</h2>
        <div class="muted small">Combinaison de la manette qui ramène la session au menu Switch.</div>
      </div>
      <label class="switch" title="Activer"><input v-model="form.enabled" type="checkbox" /><span></span></label>
    </div>

    <div class="combo" :class="{ off: !form.enabled }">
      <div>
        <label>Maintenir</label>
        <div class="row">
          <button v-for="m in MODIFIERS" :key="m.id" type="button" class="pick" :class="{ primary: form.modifier === m.id }"
                  :disabled="!form.enabled" @click="form.modifier = m.id">
            <b>{{ m.label }}</b><span class="small">{{ m.hint }}</span>
          </button>
        </div>
      </div>
      <div class="plus">+</div>
      <div>
        <label>Appuyer sur</label>
        <div class="row">
          <button v-for="b in BUTTONS" :key="b.id" type="button" class="face" :class="{ selected: form.button === b.id }"
                  :style="{ '--c': b.color }" :disabled="!form.enabled" :title="`${b.label} (${b.hint})`"
                  @click="form.button = b.id">{{ b.label }}</button>
        </div>
      </div>
    </div>

    <div class="muted small" style="margin-top:12px">
      <template v-if="form.enabled">
        <b>{{ modLabel }} + {{ btnLabel }}</b>, puis relâcher : la session revient au menu HOME.
        Lettres telles qu'imprimées sur une manette Xbox.
        <template v-if="form.modifier === 'guide'">
          Guide seul ouvre déjà le menu HOME dans Eden ; le raccourci Eden « Home + {{ { a: 'B', b: 'A', x: 'Y', y: 'X' }[form.button] }} »
          est désactivé dans les sessions pour ne pas se déclencher en même temps.
        </template>
      </template>
      <template v-else>Désactivé : seul le bouton Guide ramène au menu HOME.</template>
    </div>

    <div v-if="dirty" class="row end" style="margin-top:12px">
      <button type="button" class="ghost" @click="form = { ...saved }">Annuler</button>
      <button type="button" class="primary" @click="save">💾 Enregistrer</button>
    </div>
  </div>
</template>

<style scoped>
.combo { display: flex; align-items: flex-end; gap: 18px; flex-wrap: wrap; margin-top: 16px; }
.combo.off { opacity: .45; }
.plus { font-size: 26px; font-weight: 700; color: var(--muted); padding-bottom: 10px; }
.pick { flex-direction: column; align-items: flex-start; gap: 0; min-width: 150px; }
.face {
  width: 48px; height: 48px; border-radius: 50%; justify-content: center; padding: 0;
  font-weight: 700; font-size: 18px; color: var(--c); border: 2px solid var(--line); background: var(--bg-2);
}
.face.selected { background: var(--c); color: #0e0f14; border-color: var(--c); box-shadow: 0 0 14px var(--c); }
</style>
