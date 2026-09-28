import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'

const routes = [
  { path: '/', component: () => import('./views/Dashboard.vue'), meta: { title: 'Tableau de bord' } },
  { path: '/appairage', component: () => import('./views/Pairing.vue'), meta: { title: 'Appairage' } },
  { path: '/sessions', component: () => import('./views/Sessions.vue'), meta: { title: 'Sessions' } },
  { path: '/applications', component: () => import('./views/Apps.vue'), meta: { title: 'Applications' } },
  { path: '/applications/:profile/:index', component: () => import('./views/AppConfig.vue'), meta: { title: 'Configuration' } },
  { path: '/emulateurs', component: () => import('./views/Emulators.vue'), meta: { title: 'Émulateurs' } },
  { path: '/maintenance', component: () => import('./views/Maintenance.vue'), meta: { title: 'Maintenance' } },
]

const router = createRouter({ history: createWebHistory(), routes })
router.afterEach(to => { document.title = `${to.meta.title} · Wolfy` })

createApp(App).use(router).mount('#app')
