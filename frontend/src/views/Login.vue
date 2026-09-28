<script setup>
import { ref } from 'vue'
import { api } from '../api'

defineProps({ configured: Boolean })
const emit = defineEmits(['done'])
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await api.post('/auth/login', { password: password.value })
    emit('done')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height:100vh;display:grid;place-items:center;padding:16px">
    <form class="card" style="width:min(380px,100%);padding:28px" @submit.prevent="submit">
      <div class="brand" style="justify-content:center;padding-bottom:22px">
        <img src="/wolfy.svg" alt="" style="width:42px;height:42px" />
        <div style="font-size:24px">Wolfy<small>Administration de Wolf</small></div>
      </div>
      <div v-if="!configured" class="alert warn" style="margin-bottom:14px">
        Aucun mot de passe configuré : définis <code>WOLFY_ADMIN_PASSWORD</code> dans le fichier <code>.env</code>.
      </div>
      <div class="field">
        <label>Mot de passe administrateur</label>
        <input v-model="password" type="password" autofocus autocomplete="current-password" />
      </div>
      <div v-if="error" class="alert bad" style="margin-bottom:14px">{{ error }}</div>
      <button class="primary" style="width:100%;justify-content:center" :disabled="loading || !password">
        {{ loading ? 'Connexion…' : 'Se connecter' }}
      </button>
    </form>
  </div>
</template>
