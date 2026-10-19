<script setup>
import { ref } from 'vue'
import { api } from '../api'

// setup: no account yet, this form creates the admin one (asking WOLFY_ADMIN_PASSWORD when it is set)
const props = defineProps({ setup: Boolean, setupPassword: Boolean })
const emit = defineEmits(['done'])
const name = ref('')
const password = ref('')
const confirm = ref('')
const envPassword = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  if (props.setup && password.value !== confirm.value) {
    error.value = 'Les deux mots de passe ne correspondent pas'
    return
  }
  loading.value = true
  try {
    if (props.setup) {
      await api.post('/auth/setup', { name: name.value, password: password.value, setup_password: envPassword.value })
    } else {
      await api.post('/auth/login', { name: name.value, password: password.value })
    }
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
      <div class="brand" style="justify-content:center;padding-bottom:24px">
        <img src="/wolfy.svg" alt="" style="width:44px;height:44px" />
        <div><div class="brand-name" style="font-size:24px">Wolfy</div><div class="brand-sub">Administration de Wolf</div></div>
      </div>
      <template v-if="setup">
        <h2 style="margin:0 0 4px">Compte administrateur</h2>
        <p class="muted small" style="margin:0 0 16px">
          Premier passage : crée le compte qui a accès à tout. Les autres comptes s'ajoutent ensuite dans Paramètres.
        </p>
        <div v-if="setupPassword" class="field">
          <label for="env-password">Mot de passe actuel (<code>WOLFY_ADMIN_PASSWORD</code>)</label>
          <input id="env-password" v-model="envPassword" type="password" autocomplete="off" />
        </div>
      </template>
      <div class="field">
        <label for="login-name">Identifiant</label>
        <input id="login-name" v-model="name" autofocus autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="32" />
      </div>
      <div class="field">
        <label for="login-password">{{ setup ? 'Nouveau mot de passe (8 caractères min.)' : 'Mot de passe' }}</label>
        <input id="login-password" v-model="password" type="password" maxlength="200"
               :autocomplete="setup ? 'new-password' : 'current-password'" />
      </div>
      <div v-if="setup" class="field">
        <label for="login-confirm">Confirmer le mot de passe</label>
        <input id="login-confirm" v-model="confirm" type="password" autocomplete="new-password" maxlength="200" />
      </div>
      <div v-if="error" class="alert bad" style="margin-bottom:14px"><Icon name="alert" /><div>{{ error }}</div></div>
      <button class="primary" style="width:100%;justify-content:center"
              :disabled="loading || !name.trim() || !password || (setup && (password.length < 8 || (setupPassword && !envPassword)))">
        {{ loading ? 'Connexion…' : setup ? 'Créer le compte' : 'Se connecter' }}
      </button>
    </form>
  </div>
</template>
