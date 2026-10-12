<script setup>
// Application cover: the platform color with dots and a big initial, or the image the user uploaded
// (the default covers of backend/wolfy/covers stay for Moonlight only).
import { computed } from 'vue'
import { coverUrl } from '../api'

const props = defineProps({ app: Object, label: { type: Boolean, default: true } })

const DEFAULTS = ['switch', 'playstation', 'wii', 'steam']
const BY_EMULATOR = { eden: 'switch', retroarch: 'playstation', 'gow-retroarch': 'playstation', dolphin: 'wii', steam: 'steam' }

const file = computed(() => (props.app?.icon || '').split('/').pop().replace(/\.png$/, ''))
const custom = computed(() => props.app?.icon && !DEFAULTS.includes(file.value))
const platform = computed(() => BY_EMULATOR[props.app?.emulator] || (DEFAULTS.includes(file.value) ? file.value : 'other'))
</script>

<template>
  <div class="plat" :class="[`plat-${platform}`, { 'has-img': custom }]">
    <img v-if="custom" :src="coverUrl(app.icon)" alt="" loading="lazy" />
    <span class="glyph">{{ (app?.title || '?').charAt(0).toUpperCase() }}</span>
    <span v-if="label && !custom" class="label">{{ app?.title }}</span>
  </div>
</template>
