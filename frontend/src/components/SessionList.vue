<script setup>
import { act, api } from '../api'

defineProps({ sessions: Array })
const emit = defineEmits(['changed'])

const sid = s => String(s.session_id ?? s.client_id ?? s.id)

function res(s) {
  const w = s.video_width ?? s.display_mode?.width
  const h = s.video_height ?? s.display_mode?.height
  const fps = s.video_refresh_rate ?? s.display_mode?.refreshRate
  return w ? `${w}×${h}${fps ? ` @${fps}` : ''}` : ''
}

async function stop(s) {
  if (!confirm(`Arrêter la session « ${s.app_title || s.app_id} » de ${s.client_name || s.client_ip || 'cet appareil'} ?`)) return
  await act('Arrêt de la session', () => api.post('/sessions/stop', { session_id: sid(s) }), 'Session arrêtée')
  emit('changed')
}
</script>

<template>
  <div v-if="!sessions.length" class="empty">
    <div class="icon"><Icon name="radio" /></div>
    <div class="title">Aucune session en cours</div>
    <div class="text">Lance une application depuis Moonlight pour la voir ici.</div>
  </div>
  <div v-else class="table-wrap cards">
    <table>
      <thead><tr><th>Application</th><th>Appareil</th><th>Flux</th><th></th></tr></thead>
      <tbody>
        <tr v-for="s in sessions" :key="sid(s)">
          <td><b>{{ s.app_title || s.app_id }}</b></td>
          <td>
            {{ s.client_name || 'Appareil inconnu' }}
            <div class="muted small mono">{{ s.client_ip }}</div>
          </td>
          <td>
            <span v-if="res(s)" class="badge">{{ res(s) }}</span>
            <span v-if="s.audio_channel_count" class="badge">{{ s.audio_channel_count }} canaux</span>
          </td>
          <td class="act"><button class="danger sm" @click="stop(s)"><Icon name="stop" />Arrêter</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
