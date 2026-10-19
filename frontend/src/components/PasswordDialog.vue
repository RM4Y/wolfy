<script setup>
import { ref } from 'vue'
import { act, api } from '../api'

// the logged-in account changes its own password
const emit = defineEmits(['close'])
const current = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')

async function save() {
  error.value = ''
  if (password.value !== confirm.value) {
    error.value = 'Les deux mots de passe ne correspondent pas'
    return
  }
  const r = await act('Changement du mot de passe',
    () => api.post('/auth/password', { current: current.value, password: password.value }), 'Mot de passe changé')
  if (r) emit('close')
}
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <form class="modal narrow" @submit.prevent="save">
      <h2>Mon mot de passe</h2>
      <div class="field">
        <label for="pw-current">Mot de passe actuel</label>
        <input id="pw-current" v-model="current" type="password" autocomplete="current-password" autofocus />
      </div>
      <div class="field">
        <label for="pw-new">Nouveau mot de passe (8 caractères min.)</label>
        <input id="pw-new" v-model="password" type="password" autocomplete="new-password" maxlength="200" />
      </div>
      <div class="field">
        <label for="pw-confirm">Confirmer</label>
        <input id="pw-confirm" v-model="confirm" type="password" autocomplete="new-password" maxlength="200" />
      </div>
      <div v-if="error" class="alert bad" style="margin-bottom:14px"><Icon name="alert" /><div>{{ error }}</div></div>
      <div class="row" style="gap:8px;justify-content:flex-end">
        <button type="button" class="ghost" @click="emit('close')">Annuler</button>
        <button type="submit" class="primary" :disabled="!current || password.length < 8"><Icon name="save" />Enregistrer</button>
      </div>
    </form>
  </div>
</template>
