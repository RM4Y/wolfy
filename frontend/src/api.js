import { reactive } from 'vue'

export const ui = reactive({ toasts: [], busy: '' })

export function toast(message, kind = 'ok') {
  const t = { id: Math.random(), message, kind }
  ui.toasts.push(t)
  setTimeout(() => ui.toasts.splice(ui.toasts.indexOf(t), 1), kind === 'error' ? 7000 : 3500)
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

async function request(method, path, body) {
  const opts = { method, headers: {} }
  if (body instanceof FormData) opts.body = body
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(`/api${path}`, opts)
  const data = await resp.json().catch(() => ({}))
  if (resp.status === 401 && path !== '/auth/login') {
    window.dispatchEvent(new Event('wolfy:logout'))
  }
  if (!resp.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail
    throw new ApiError(resp.status, detail || `Erreur ${resp.status}`)
  }
  return data
}

export const api = {
  get: p => request('GET', p),
  post: (p, b = {}) => request('POST', p, b),
  put: (p, b) => request('PUT', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: p => request('DELETE', p),
}

// Runs an action with a global busy overlay + toast; returns undefined on error.
export async function act(label, fn, success) {
  ui.busy = label
  try {
    const r = await fn()
    if (success) toast(success)
    return r
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    ui.busy = ''
  }
}

export function ago(iso) {
  if (!iso) return '—'
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return "à l'instant"
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`
  return `il y a ${Math.floor(s / 86400)} j`
}

export function bytes(n) {
  if (n == null) return '—'
  const u = ['o', 'Ko', 'Mo', 'Go']
  let i = 0
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}

export function coverUrl(icon) {
  if (!icon) return ''
  if (/^https?:/.test(icon)) return icon
  return `/api/covers/${icon.split('/').pop()}`
}
