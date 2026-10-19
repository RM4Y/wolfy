import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { allowed, home, session } from './api'
import Icon from './components/Icon.vue'
import './style.css'

const routes = [
  { path: '/', component: () => import('./views/Dashboard.vue'), meta: { title: 'Tableau de bord', tab: 'dashboard' } },
  { path: '/appairage', component: () => import('./views/Pairing.vue'), meta: { title: 'Appairage', tab: 'pairing' } },
  { path: '/sessions', component: () => import('./views/Sessions.vue'), meta: { title: 'Sessions', tab: 'sessions' } },
  { path: '/applications', component: () => import('./views/Apps.vue'), meta: { title: 'Applications' } },
  { path: '/applications/:profile/:index', component: () => import('./views/AppConfig.vue'), meta: { title: 'Configuration' } },
  { path: '/jeux', component: () => import('./views/Games.vue'), meta: { title: 'Mes jeux', tab: 'games' } },
  { path: '/emulateurs', component: () => import('./views/Emulators.vue'), meta: { title: 'Émulateurs' } },
  { path: '/parametres', component: () => import('./views/Maintenance.vue'), meta: { title: 'Paramètres' } },
  { path: '/maintenance', redirect: '/parametres' },
]

const router = createRouter({ history: createWebHistory(), routes })
// an account other than an admin only reaches the tabs it was given (the API checks them too)
router.beforeEach(to => (!session.user || allowed(to) || !home() || home() === to.path ? true : home()))
router.afterEach(to => { document.title = `${to.meta.title} · Wolfy` })

createApp(App).use(router).component('Icon', Icon).mount('#app')
