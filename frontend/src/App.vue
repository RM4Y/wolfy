<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { allowed, api, can, home, isAdmin, session, ui } from './api'
import Login from './views/Login.vue'
import PasswordDialog from './components/PasswordDialog.vue'

const state = ref('loading') // loading | login | app
const setup = ref({ setup: false, setupPassword: false })
const passwordDialog = ref(false)
const pending = ref(0)
const sessions = ref(0)
let timer

async function checkAuth() {
  const r = await api.get('/auth')
  setup.value = { setup: r.setup, setupPassword: r.setup_password }
  session.user = r.user
  state.value = r.logged_in ? 'app' : 'login'
  if (!r.logged_in) return
  // the page opened may not be one of this account's
  if (!allowed(route) && home() && home() !== route.path) router.replace(home())
  poll()
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
  onLogout()
}

function onLogout() { session.user = null; state.value = 'login'; checkAuth() }

// Nuit by default, Jour on demand (index.html applies the saved one before the first paint)
const theme = ref(document.documentElement.dataset.theme || 'dark')
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = theme.value
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme.value === 'dark' ? '#07060f' : '#f3f2fa')
  try { localStorage.setItem('wolfy-theme', theme.value) } catch { /* private window */ }
}

// mobile: "Plus" opens a sheet with the pages that are not in the tab bar
const more = ref(false)
const route = useRoute()
const router = useRouter()
watch(() => route.path, () => { more.value = false })
const inMore = computed(() => ['/appairage', '/jeux', '/parametres'].some(p => route.path.startsWith(p)))
onMounted(() => { checkAuth(); window.addEventListener('wolfy:logout', onLogout) })
onUnmounted(() => { clearTimeout(timer); window.removeEventListener('wolfy:logout', onLogout) })
</script>

<template>
  <div class="aurora" aria-hidden="true"><i></i><i></i><i></i></div>
  <Login v-if="state === 'login'" :setup="setup.setup" :setup-password="setup.setupPassword" @done="checkAuth" />
  <div v-else-if="state === 'app'" class="shell">
    <aside class="side">
      <div class="brand">
        <img src="/wolfy.svg" alt="" />
        <div><div class="brand-name">Wolfy</div><div class="brand-sub">{{ session.user.name }}{{ isAdmin() ? ' · admin' : '' }}</div></div>
      </div>
      <nav class="nav">
        <router-link v-if="can('dashboard')" to="/" exact-active-class="router-link-active" active-class=""><Icon name="home" />Tableau de bord</router-link>
        <router-link v-if="can('pairing')" to="/appairage"><Icon name="key" />Appairage
          <span v-if="pending" class="count alert pulse">{{ pending }}</span>
        </router-link>
        <router-link v-if="can('sessions')" to="/sessions"><Icon name="radio" />Sessions
          <span v-if="sessions" class="count">{{ sessions }}</span>
        </router-link>
        <router-link v-if="isAdmin()" to="/applications" :class="{ 'router-link-active': route.path.startsWith('/applications') }"><Icon name="gamepad" />Applications</router-link>
        <router-link v-if="can('games')" to="/jeux"><Icon name="library" />Mes jeux</router-link>
        <router-link v-if="isAdmin()" to="/emulateurs"><Icon name="layers" />Émulateurs</router-link>
        <router-link v-if="isAdmin()" to="/parametres"><Icon name="sliders" />Paramètres</router-link>
      </nav>
      <div class="side-foot">
        <button class="ghost" @click="passwordDialog = true"><Icon name="lock" />Mon mot de passe</button>
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
      <div v-if="!home()" class="card empty">
        <div class="icon"><Icon name="lock" /></div><div class="title">Aucune page pour ce compte</div>
        <div class="muted">Demande à l'administrateur de t'en ouvrir dans Paramètres › Comptes.</div>
      </div>
      <router-view v-else @refresh="poll" />
    </main>

    <nav class="tabbar">
      <router-link v-if="can('dashboard')" to="/" exact-active-class="router-link-active" active-class=""><Icon name="home" />Accueil</router-link>
      <router-link v-if="can('sessions')" to="/sessions"><Icon name="radio" />Sessions<span v-if="sessions" class="dot ok"></span></router-link>
      <router-link v-if="isAdmin()" to="/applications" :class="{ 'router-link-active': route.path.startsWith('/applications') }"><Icon name="gamepad" />Applis</router-link>
      <router-link v-if="isAdmin()" to="/emulateurs"><Icon name="layers" />Émulateurs</router-link>
      <!-- an account: its other tabs in the bar itself, the sheet keeps the rest -->
      <router-link v-if="!isAdmin() && can('pairing')" to="/appairage"><Icon name="key" />Appairage<span v-if="pending" class="dot accent pulse"></span></router-link>
      <router-link v-if="!isAdmin() && can('games')" to="/jeux"><Icon name="library" />Mes jeux</router-link>
      <button type="button" :class="{ active: more || (isAdmin() && inMore) }" @click="more = !more">
        <Icon name="more" />Plus<span v-if="pending && isAdmin()" class="dot accent pulse"></span>
      </button>
    </nav>
    <template v-if="more">
      <div class="sheet-back" @click="more = false"></div>
      <div class="sheet nav">
        <template v-if="isAdmin()">
          <router-link to="/appairage"><Icon name="key" />Appairage
            <span v-if="pending" class="count alert">{{ pending }}</span>
          </router-link>
          <router-link to="/jeux"><Icon name="library" />Mes jeux</router-link>
          <router-link to="/parametres"><Icon name="sliders" />Paramètres</router-link>
        </template>
        <a href="#" @click.prevent="passwordDialog = true; more = false"><Icon name="lock" />Mon mot de passe</a>
        <a href="#" @click.prevent="logout"><Icon name="logout" />Déconnexion</a>
      </div>
    </template>
    <PasswordDialog v-if="passwordDialog" @close="passwordDialog = false" />
  </div>

  <div v-if="ui.busy" class="busy"><div class="box"><div class="spinner"></div>{{ ui.busy }}…</div></div>
  <div class="toasts">
    <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
  </div>
</template>
