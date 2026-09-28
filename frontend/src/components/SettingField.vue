<script setup>
// One emulator setting: label, help, widget adapted to its type, default/reset state.
import { computed, ref } from 'vue'

const props = defineProps({ item: Object, value: null, modified: Boolean })
const emit = defineEmits(['update', 'reset'])
const reveal = ref(false)
const showHelp = ref(false)

const it = computed(() => props.item)
const isDefault = computed(() => it.value.default !== undefined && it.value.default !== null
  && props.value === it.value.default)
const slider = computed(() => it.value.type === 'int' && it.value.min != null && it.value.max != null
  && it.value.max - it.value.min <= 1000)
const shortHelp = computed(() => (it.value.help || '').trim())

function set(v) { emit('update', v) }
function num(v) { const n = Number(v); if (!Number.isNaN(n)) set(n) }
</script>

<template>
  <div class="setting" :class="{ modified, forced: it.forced }">
    <div class="setting-text">
      <div class="setting-label">
        {{ it.label || it.key }}
        <span v-if="modified" class="badge accent">modifié</span>
        <span v-else-if="isDefault" class="badge">défaut</span>
      </div>
      <div class="mono muted setting-key">[{{ it.section }}] {{ it.key }}</div>
      <div v-if="it.forced" class="small" style="color:var(--warn)">🔒 Imposé à chaque session Wolf : {{ it.forced }}</div>
      <div v-if="shortHelp" class="small muted help-text" :class="{ open: showHelp }" @click="showHelp = !showHelp">
        {{ shortHelp }}
      </div>
    </div>

    <div class="setting-input">
      <label v-if="it.type === 'bool'" class="switch">
        <input type="checkbox" :checked="value" :disabled="!!it.forced" @change="set($event.target.checked)" />
        <span></span>
      </label>

      <select v-else-if="it.type === 'enum' && it.options?.length" :value="value" :disabled="!!it.forced"
              @change="num($event.target.value)">
        <option v-for="o in it.options" :key="o.value" :value="o.value">{{ o.label }}</option>
        <option v-if="!it.options.some(o => o.value === value)" :value="value">Valeur {{ value }}</option>
      </select>

      <select v-else-if="it.type === 'choice' && it.options?.length" :value="value" :disabled="!!it.forced"
              @change="set($event.target.value)">
        <option v-for="o in it.options" :key="o.value" :value="o.value">{{ o.label }}</option>
        <option v-if="!it.options.some(o => o.value === value)" :value="value">{{ value }}</option>
      </select>

      <div v-else-if="slider" class="row" style="flex-wrap:nowrap">
        <input type="range" :min="it.min" :max="it.max" :value="value" :disabled="!!it.forced"
               @input="num($event.target.value)" />
        <input type="number" :min="it.min" :max="it.max" :value="value" style="width:90px" :disabled="!!it.forced"
               @change="num($event.target.value)" />
        <span v-if="it.percent" class="muted">%</span>
      </div>

      <input v-else-if="it.type === 'int' || it.type === 'enum'" type="number" :value="value"
             :disabled="!!it.forced" @change="num($event.target.value)" />
      <input v-else-if="it.type === 'float'" type="number" step="0.01" :value="value"
             :disabled="!!it.forced" @change="num($event.target.value)" />

      <div v-else class="row" style="flex-wrap:nowrap">
        <input :type="it.secret && !reveal ? 'password' : 'text'" class="mono" :value="value"
               :disabled="!!it.forced" @change="set($event.target.value)" />
        <button v-if="it.secret" type="button" class="ghost sm" @click="reveal = !reveal">👁</button>
      </div>

      <button v-if="!it.forced && it.default != null && !isDefault" type="button" class="ghost sm reset"
              title="Remettre la valeur par défaut" @click="emit('reset')">↺ défaut</button>
    </div>
  </div>
</template>

<style scoped>
.setting {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 340px); gap: 16px;
  padding: 12px 14px; border-radius: 10px; align-items: center;
}
.setting:hover { background: var(--bg-2); }
.setting.modified { background: rgba(124, 92, 255, .08); box-shadow: inset 3px 0 0 var(--accent); }
.setting-label { font-weight: 500; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.setting-key { font-size: 11px; margin-top: 1px; word-break: break-all; }
.help-text { margin-top: 4px; white-space: pre-line; cursor: pointer; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.help-text.open { -webkit-line-clamp: unset; }
.setting-input { display: flex; flex-direction: column; align-items: stretch; gap: 4px; }
.setting-input .switch { align-self: flex-end; }
.reset { align-self: flex-end; }
@media (max-width: 700px) { .setting { grid-template-columns: 1fr; } }
</style>
