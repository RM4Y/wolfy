<script setup>
// Follows a background job (image build/pull) until it finishes.
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'

const props = defineProps({ jobId: String })
const emit = defineEmits(['close', 'done'])
const job = ref(null)
const box = ref(null)
let timer

async function poll() {
  try {
    job.value = await api.get(`/jobs/${props.jobId}`)
  } catch { /* keep last state */ }
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
  if (job.value?.status === 'running') timer = setTimeout(poll, 1000)
  else emit('done', job.value)
}

onMounted(poll)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <div class="modal">
      <div class="row between" style="margin-bottom:12px">
        <h2 style="margin:0">{{ job?.title || 'Tâche' }}</h2>
        <span v-if="job" class="badge" :class="{ ok: job.status === 'success', bad: job.status === 'error', warn: job.status === 'running' }">
          {{ { running: 'en cours…', success: 'terminé', error: 'échec' }[job.status] }}
        </span>
      </div>
      <div ref="box" class="logbox">{{ job?.log?.join('\n') || '…' }}</div>
      <div class="row end" style="margin-top:12px">
        <button @click="emit('close')">{{ job?.status === 'running' ? 'Continuer en arrière-plan' : 'Fermer' }}</button>
      </div>
    </div>
  </div>
</template>
