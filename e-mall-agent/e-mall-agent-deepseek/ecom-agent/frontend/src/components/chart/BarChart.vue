<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CHART_AXIS_COLOR, CHART_COLORS, CHART_TEXT_COLOR, type ChartOption } from './echarts'
import { useChart } from './useChart'

const props = defineProps<{
  categories: string[]
  series: Array<{ name: string; data: number[]; color?: string }>
  height?: string
  horizontal?: boolean
  valueFormatter?: (value: number) => string
}>()

const height = computed(() => props.height ?? '280px')

const option = computed<ChartOption>(() => {
  const horizontal = props.horizontal === true
  const categoryAxis = {
    type: 'category' as const,
    data: props.categories,
    axisLine: { lineStyle: { color: CHART_AXIS_COLOR } },
    axisTick: { show: false },
    axisLabel: { color: CHART_TEXT_COLOR, fontSize: 11 },
  }
  const valueAxis = {
    type: 'value' as const,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: CHART_AXIS_COLOR, type: 'dashed' as const } },
    axisLabel: { color: CHART_TEXT_COLOR, fontSize: 11 },
  }

  return {
    color: [...CHART_COLORS],
    grid: { left: 8, right: 20, top: 16, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: props.valueFormatter,
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0', fontSize: 12 },
    },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: props.series.map((item, index) => ({
      type: 'bar' as const,
      name: item.name,
      data: item.data,
      barMaxWidth: 26,
      itemStyle: {
        color: item.color ?? CHART_COLORS[index % CHART_COLORS.length],
        borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
      },
    })),
  }
})

const { el } = useChart(() => option.value)
</script>

<style scoped>
.chart {
  width: 100%;
}
</style>
