<script setup>
import { onMounted, ref } from 'vue'
import { act, api, session, TABS } from '../api'

// Paramètres › Comptes: an admin sees everything, another account only the tabs ticked for it
const users = ref([])
const editing = ref(null)  // { name, isNew, password, role, tabs }

async function load() {
  users.value = (await act('Chargement des comptes', () => api.get('/users')))?.users || users.value
}

function add() {
  editing.value = { name: '', isNew: true, password: '', role: 'user', tabs: Object.keys(TABS) }
}

function edit(u) {
  editing.value = { name: u.name, isNew: false, password: '', role: u.role, tabs: [...u.tabs] }
}

async function save() {
  const e = editing.value
  const body = { role: e.role, tabs: e.role === 'admin' ? [] : e.tabs }
  const r = e.isNew
    ? await act('Création du compte', () => api.post('/users', { ...body, name: e.name, password: e.password }), 'Compte créé')
    : await act('Enregistrement', () => api.put(`/users/${encodeURIComponent(e.name)}`, { ...body, password: e.password || null }), 'Compte enregistré')
  if (!r) return
  editing.value = null
  load()
}

async function remove(u) {
  if (!confirm(`Supprimer le compte ${u.name} ?`)) return
  if (await act('Suppression', () => api.del(`/users/${encodeURIComponent(u.name)}`), 'Compte supprimé')) load()
}

onMounted(load)
</script>

<template>
  <div class="card">
    <div class="row" style="margin-bottom:4px">
      <h2 style="margin:0">Comptes</h2>
      <div class="spacer"></div>
      <button class="sm" @click="add"><Icon name="plus" />Ajouter</button>
    </div>
    <div class="muted small" style="margin-bottom:12px">
      Un administrateur a accès à tout. Un autre compte ne voit que les onglets cochés pour lui.
    </div>
    <div class="table-wrap">
      <table>
        <tbody>
          <tr v-for="u in users" :key="u.name">
            <td style="width:1%;white-space:nowrap"><Icon name="user" /> <b>{{ u.name }}</b>
              <span v-if="u.name === session.user?.name" class="muted small"> (toi)</span></td>
            <td>
              <span v-if="u.role === 'admin'" class="badge accent">Administrateur</span>
              <span v-else-if="!u.tabs.length" class="muted small">Aucun onglet</span>
              <span v-else class="muted small">{{ u.tabs.map(t => TABS[t][1]).join(' · ') }}</span>
            </td>
            <td style="text-align:right;white-space:nowrap">
              <button class="sm ghost" @click="edit(u)"><Icon name="edit" />Modifier</button>
              <button v-if="u.name !== session.user?.name" class="sm ghost" @click="remove(u)"><Icon name="trash" /></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="editing" class="modal-back" @click.self="editing = null">
    <form class="modal narrow" @submit.prevent="save">
      <h2>{{ editing.isNew ? 'Nouveau compte' : `Compte ${editing.name}` }}</h2>
      <div v-if="editing.isNew" class="field">
        <label for="acc-name">Identifiant</label>
        <input id="acc-name" v-model="editing.name" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="32" autofocus />
      </div>
      <div class="field">
        <label for="acc-password">{{ editing.isNew ? 'Mot de passe (8 caractères min.)' : 'Nouveau mot de passe (vide : inchangé)' }}</label>
        <input id="acc-password" v-model="editing.password" type="password" autocomplete="new-password" maxlength="200" />
      </div>
      <div class="field">
        <label for="acc-role">Rôle</label>
        <select id="acc-role" v-model="editing.role">
          <option value="user">Utilisateur</option>
          <option value="admin">Administrateur (accès à tout)</option>
        </select>
      </div>
      <div v-if="editing.role === 'user'" class="field">
        <label>Onglets</label>
        <label v-for="(t, key) in TABS" :key="key" class="check">
          <input v-model="editing.tabs" type="checkbox" :value="key" />{{ t[1] }}
        </label>
      </div>
      <div class="row" style="gap:8px;justify-content:flex-end">
        <button type="button" class="ghost" @click="editing = null">Annuler</button>
        <button type="submit" class="primary"
                :disabled="(editing.isNew && !editing.name.trim()) || ((editing.isNew || editing.password) && editing.password.length < 8)">
          <Icon name="save" />Enregistrer
        </button>
      </div>
    </form>
  </div>
</template>
