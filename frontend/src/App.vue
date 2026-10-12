<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
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

// Nuit by default, Jour on demand (index.html applies the saved one before the first paint)
const theme = ref(document.documentElement.dataset.theme || 'dark')
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = theme.value
  try { localStorage.setItem('wolfy-theme', theme.value) } catch { /* private window */ }
}

// mobile: "Plus" opens a sheet with the pages that are not in the tab bar
const more = ref(false)
const route = useRoute()
watch(() => route.path, () => { more.value = false })
const inMore = computed(() => ['/appairage', '/parametres'].some(p => route.path.startsWith(p)))
onMounted(() => { checkAuth(); window.addEventListener('wolfy:logout', onLogout) })
onUnmounted(() => { clearTimeout(timer); window.removeEventListener('wolfy:logout', onLogout) })
</script>

<template>
  <div class="aurora" aria-hidden="true"><i></i><i></i><i></i></div>
  <Login v-if="state === 'login'" :configured="configured" @done="checkAuth" />
  <div v-else-if="state === 'app'" class="shell">
    <aside class="side">
      <div class="brand">
        <img src="/wolfy.svg" alt="" />
        <div><div class="brand-name">Wolfy</div><div class="brand-sub">Admin Wolf</div></div>
      </div>
      <nav class="nav">
        <router-link to="/" exact-active-class="router-link-active" active-class=""><Icon name="home" />Tableau de bord</router-link>
        <router-link to="/appairage"><Icon name="key" />Appairage
          <span v-if="pending" class="count alert pulse">{{ pending }}</span>
        </router-link>
        <router-link to="/sessions"><Icon name="radio" />Sessions
          <span v-if="sessions" class="count">{{ sessions }}</span>
        </router-link>
        <router-link to="/applications" :class="{ 'router-link-active': route.path.startsWith('/applications') }"><Icon name="gamepad" />Applications</router-link>
        <router-link to="/emulateurs"><Icon name="layers" />Émulateurs</router-link>
        <router-link to="/parametres"><Icon name="sliders" />Paramètres</router-link>
      </nav>
      <div class="side-foot">
        <button class="ghost" @click="toggleTheme"><Icon :name="theme === 'dark' ? 'sun' : 'moon'" />{{ theme === 'dark' ? 'Thème Jour' : 'Thème Nuit' }}</button>
        <button class="ghost" @click="logout"><Icon name="logout" />Déconnexion</button>
      </div>
    </aside>

    <header class="topbar">
      <div class="brand">
        <img src="/wolfy.svg" alt="" />
        <div class="brand-name">Wolfy</div>
      </div>
      <button class="ghost icon" :aria-label="theme === 'dark' ? 'Thème Jour' : 'Thème Nuit'" @click="toggleTheme">
        <Icon :name="theme === 'dark' ? 'sun' : 'moon'" />
      </button>
    </header>

    <main>
      <router-view @refresh="poll" />
    </main>

    <nav class="tabbar">
      <router-link to="/" exact-active-class="router-link-active" active-class=""><Icon name="home" />Accueil</router-link>
      <router-link to="/sessions"><Icon name="radio" />Sessions<span v-if="sessions" class="dot ok"></span></router-link>
      <router-link to="/applications" :class="{ 'router-link-active': route.path.startsWith('/applications') }"><Icon name="gamepad" />Applis</router-link>
      <router-link to="/emulateurs"><Icon name="layers" />Émulateurs</router-link>
      <button type="button" :class="{ active: more || inMore }" @click="more = !more">
        <Icon name="more" />Plus<span v-if="pending" class="dot accent pulse"></span>
      </button>
    </nav>
    <template v-if="more">
      <div class="sheet-back" @click="more = false"></div>
      <div class="sheet nav">
        <router-link to="/appairage"><Icon name="key" />Appairage
          <span v-if="pending" class="count alert">{{ pending }}</span>
        </router-link>
        <router-link to="/parametres"><Icon name="sliders" />Paramètres</router-link>
        <a href="#" @click.prevent="logout"><Icon name="logout" />Déconnexion</a>
      </div>
    </template>
  </div>

  <div v-if="ui.busy" class="busy"><div class="box"><div class="spinner"></div>{{ ui.busy }}…</div></div>
  <div class="toasts">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
  </div>
</template>
