import type { Action } from 'svelte/action'

/** Grows a textarea to fit its content. Pass the bound value so it refits on change. */
export const autosize: Action<HTMLTextAreaElement, string | undefined> = (node) => {
  function fit() {
    node.style.height = 'auto'
    node.style.height = `${node.scrollHeight + 2}px`
  }
  node.addEventListener('input', fit)
  requestAnimationFrame(fit)
  return {
    update: fit,
    destroy: () => node.removeEventListener('input', fit),
  }
}
