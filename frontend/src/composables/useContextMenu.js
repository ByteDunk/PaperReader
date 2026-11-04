import { nextTick, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'

// Paper and bookmark menus share positioning, keyboard navigation and lifetime.
export function useContextMenu({ selector, height }) {
  const id = ref('')
  const style = ref({})
  const menu = ref(null)
  let trigger

  function close(restoreFocus = false) {
    id.value = ''
    if (restoreFocus) trigger?.focus()
  }

  async function toggle(event, value) {
    if (id.value === value) { close(); return }
    trigger = event.currentTarget
    const rect = trigger.getBoundingClientRect()
    style.value = {
      left: `${Math.max(8, Math.min(window.innerWidth - 152, rect.right - 144))}px`,
      top: `${rect.bottom + height < window.innerHeight ? rect.bottom + 4 : Math.max(8, rect.top - height)}px`,
    }
    id.value = value
    await nextTick()
    menu.value?.querySelector('button:not(:disabled)')?.focus()
  }

  function keydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(true) }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const buttons = [...menu.value.querySelectorAll('button:not(:disabled)')]
    const current = buttons.indexOf(event.target)
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
    buttons[index]?.focus()
  }

  function outside(event) {
    if (!event.target.closest(selector)) close()
  }

  onMounted(() => window.addEventListener('pointerdown', outside))
  onBeforeUnmount(() => window.removeEventListener('pointerdown', outside))
  onDeactivated(() => close())

  return { id, style, menu, toggle, close, keydown }
}
