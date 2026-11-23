<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CHART_COLORS, CHART_TEXT_COLOR, type ChartOption } from './echarts'
import { useChart } from './useChart'

const props = defineProps<{
  items: Array<{ name: string; value: number }>
  height?: string
  donut?: boolean
  valueFormatter?: (value: number) => string
}>()

const height = computed(() => props.height ?? '280px')

const option = computed<ChartOption>(() => ({
  color: [...CHART_COLORS],
  tooltip: {
    trigger: 'item',
    valueFormatter: props.valueFormatter,
    backgroundColor: 'rgba(15, 23, 42, 0.92)',
    borderWidth: 0,
    textStyle: { color: '#e2e8f0', fontSize: 12 },
  },
  legend: {
    bottom: 0,
    icon: 'circle',
    itemWidth: 8,
    itemHeight: 8,
    textStyle: { color: CHART_TEXT_COLOR, fontSize: 11 },
  },
  series: [
    {
      type: 'pie',
      radius: props.donut === false ? ['0%', '64%'] : ['42%', '64%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
      label: { fontSize: 11, color: CHART_TEXT_COLOR },
      data: props.items,
    },
  ],
}))

const { el } = useChart(() => option.value)
</script>

<style scoped>
.chart {
  width: 100%;
}
</style>
