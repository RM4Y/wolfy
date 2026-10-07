<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api, ui } from './api'
import Login from './views/Login.vue'

const state = ref('loading') // loading | login | app
const configured = ref(true)
const pending = ref(0)
const sessions = ref(0)
let timer

async function checkAuth() {
  const r = await api.get('/auth')
  configured.value = r.configured
  state.value = r.logged_in ? 'app' : 'login'
  if (r.logged_in) poll()
}

// badges in the nav: pending pairing requests and live sessions
async function poll() {
  clearTimeout(timer)
  if (state.value !== 'app') return
  try {
    const o = await api.get('/overview')
    pending.value = o.pending.length
    sessions.value = o.sessions.length
  } catch { /* shown by the pages themselves */ }
  timer = setTimeout(poll, 5000)
}

async function logout() {
  await api.post('/auth/logout')
  state.value = 'login'
}

function onLogout() { state.value = 'login' }
onMounted(() => { checkAuth(); window.addEventListener('wolfy:logout', onLogout) })
onUnmounted(() => { clearTimeout(timer); window.removeEventListener('wolfy:logout', onLogout) })
</script>

<template>
  <Login v-if="state === 'login'" :configured="configured" @done="checkAuth" />
  <div v-else-if="state === 'app'" class="shell">
    <aside class="side">
      <div class="brand">
        <img src="/wolfy.svg" alt="" />
        <div>Wolfy<small>Admin Wolf</small></div>
      </div>
      <nav class="nav">
        <router-link to="/">🏠 Tableau de bord</router-link>
        <router-link to="/appairage">🔑 Appairage
          <span v-if="pending" class="badge accent pulse">{{ pending }}</span>
        </router-link>
        <router-link to="/sessions">📡 Sessions
          <span v-if="sessions" class="badge ok">{{ sessions }}</span>
        </router-link>
        <router-link to="/applications">🎮 Applications</router-link>
        <router-link to="/emulateurs">🧩 Émulateurs</router-link>
        <router-link to="/parametres">⚙️ Paramètres</router-link>
      </nav>
      <div class="side-foot">
        <button class="ghost sm" @click="logout">↩ Déconnexion</button>
      </div>
    </aside>
    <main>
      <router-view @refresh="poll" />
    </main>
  </div>

  <div v-if="ui.busy" class="busy"><div class="box"><div class="spinner"></div>{{ ui.busy }}…</div></div>
  <div class="toasts">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
  </div>
</template>
