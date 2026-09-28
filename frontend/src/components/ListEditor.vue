<script setup>
// Editable list of strings (mounts, env vars, devices…)
const model = defineModel({ type: Array, default: () => [] })
defineProps({ placeholder: String })

function add() { model.value = [...model.value, ''] }
function remove(i) { model.value = model.value.filter((_, j) => j !== i) }
function set(i, v) { model.value = model.value.map((x, j) => (j === i ? v : x)) }
</script>

<template>
  <div class="stack" style="--gap:6px">
    <div v-for="(item, i) in model" :key="i" class="row" style="margin-top:6px;flex-wrap:nowrap">
      <input class="mono" :value="item" :placeholder="placeholder" @input="set(i, $event.target.value)" />
      <button type="button" class="ghost sm danger" title="Retirer" @click="remove(i)">✖</button>
    </div>
    <button type="button" class="sm" style="margin-top:6px" @click="add">＋ Ajouter</button>
  </div>
</template>
