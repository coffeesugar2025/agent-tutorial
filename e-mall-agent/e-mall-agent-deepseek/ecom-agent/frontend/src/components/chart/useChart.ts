import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { echarts, type ChartInstance, type ChartOption } from './echarts'

/** echarts 生命周期封装：初始化 / 响应式 setOption / resize / dispose */
export function useChart(option: () => ChartOption) {
  const el = ref<HTMLDivElement | null>(null)
  const chart = shallowRef<ChartInstance | null>(null)
  let observer: ResizeObserver | null = null

  function render(): void {
    const instance = chart.value
    if (!instance) return
    instance.setOption(option(), true)
  }

  function resize(): void {
    chart.value?.resize()
  }

  onMounted(() => {
    if (!el.value) return
    chart.value = echarts.init(el.value)
    render()
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => resize())
      observer.observe(el.value)
    } else {
      window.addEventListener('resize', resize)
    }
  })

  watch(option, render, { deep: true })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
    window.removeEventListener('resize', resize)
    chart.value?.dispose()
    chart.value = null
  })

  return { el, chart, render, resize }
}
