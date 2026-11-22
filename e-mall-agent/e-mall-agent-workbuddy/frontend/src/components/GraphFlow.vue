<script setup lang="ts">
import { computed } from 'vue'
import type { GraphDescription, GraphNode } from '../types'

const props = defineProps<{ graph: GraphDescription }>()

let instanceCounter = 0
const markerId = `graph-arrow-${++instanceCounter}-${Date.now().toString(36)}`

const NODE_W = 148
const NODE_H = 46
const GAP_X = 72
const GAP_Y = 28
const PAD_X = 28
const PAD_Y = 28

interface PositionedNode extends GraphNode {
  x: number
  y: number
  depth: number
}

const palette: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  agent: { fill: '#eaf1ff', stroke: '#93b4f7', text: '#1d4ed8', label: '智能体' },
  decision: { fill: '#fff6e6', stroke: '#f3cf90', text: '#b45309', label: '决策' },
  human: { fill: '#f3eaff', stroke: '#d3b5ff', text: '#7c3aed', label: '人工节点' },
  end: { fill: '#e8f7ee', stroke: '#a7dfbd', text: '#15803d', label: '终止' },
  process: { fill: '#f4f6f9', stroke: '#d7dce5', text: '#475569', label: '处理' },
}

function colorOf(kind: string) {
  return palette[kind] || palette.process
}

const layout = computed(() => {
  const nodes = props.graph.nodes || []
  const edges = props.graph.edges || []
  const depth = new Map<string, number>()
  nodes.forEach((node) => depth.set(node.id, 0))

  // Longest-path layering; the iteration cap protects against cyclic graphs.
  for (let pass = 0; pass < nodes.length; pass += 1) {
    let changed = false
    for (const edge of edges) {
      const from = depth.get(edge.source)
      const to = depth.get(edge.target)
      if (from === undefined || to === undefined) continue
      if (to < from + 1) {
        depth.set(edge.target, from + 1)
        changed = true
      }
    }
    if (!changed) break
  }

  const layers = new Map<number, GraphNode[]>()
  nodes.forEach((node) => {
    const d = depth.get(node.id) || 0
    const layer = layers.get(d) || []
    layer.push(node)
    layers.set(d, layer)
  })

  const positions = new Map<string, PositionedNode>()
  let maxRows = 1
  let maxDepth = 0
  const sortedDepths = [...layers.keys()].sort((a, b) => a - b)
  sortedDepths.forEach((d) => {
    const layer = layers.get(d) || []
    maxRows = Math.max(maxRows, layer.length)
    maxDepth = Math.max(maxDepth, d)
    layer.forEach((node, index) => {
      positions.set(node.id, {
        ...node,
        depth: d,
        x: PAD_X + d * (NODE_W + GAP_X),
        y: PAD_Y + index * (NODE_H + GAP_Y),
      })
    })
  })

  const width = PAD_X * 2 + (maxDepth + 1) * NODE_W + maxDepth * GAP_X
  const height = PAD_Y * 2 + maxRows * NODE_H + (maxRows - 1) * GAP_Y + 16

  const drawnEdges = edges
    .map((edge) => {
      const source = positions.get(edge.source)
      const target = positions.get(edge.target)
      if (!source || !target) return null
      const x1 = source.x + NODE_W
      const y1 = source.y + NODE_H / 2
      const x2 = target.x
      const y2 = target.y + NODE_H / 2
      const midX = (x1 + x2) / 2
      const midY = (y1 + y2) / 2
      const labelWidth = edge.label ? edge.label.length * 12 + 12 : 0
      return {
        key: `${edge.source}-${edge.target}`,
        path: `M ${x1} ${y1} C ${x1 + 34} ${y1}, ${x2 - 34} ${y2}, ${x2} ${y2}`,
        label: edge.label || '',
        labelX: midX,
        labelY: midY - 6,
        labelWidth,
      }
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)

  return {
    nodes: [...positions.values()],
    edges: drawnEdges,
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
  }
})

const legend = [
  { kind: 'agent', text: '智能体' },
  { kind: 'decision', text: '决策' },
  { kind: 'human', text: '人工审批' },
  { kind: 'end', text: '终止' },
  { kind: 'process', text: '处理' },
]
</script>

<template>
  <div class="graph-card card">
    <div class="graph-header">
      <div class="section-title">{{ graph.title }}</div>
      <span class="badge">{{ graph.nodes.length }} 个节点 / {{ graph.edges.length }} 条连线</span>
    </div>
    <div class="graph-scroll">
      <svg :viewBox="layout.viewBox" :width="layout.width" :height="layout.height" role="img" :aria-label="graph.title">
        <defs>
          <marker :id="markerId" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
        </defs>

        <g class="edges">
          <g v-for="edge in layout.edges" :key="edge.key">
            <path :d="edge.path" fill="none" stroke="#b8c1cf" stroke-width="1.6" :marker-end="`url(#${markerId})`" />
            <g v-if="edge.label">
              <rect :x="edge.labelX - edge.labelWidth / 2" :y="edge.labelY - 11" :width="edge.labelWidth" height="18" rx="5" fill="#ffffff" stroke="#e6e9ef" />
              <text :x="edge.labelX" :y="edge.labelY + 2" text-anchor="middle" class="edge-label">{{ edge.label }}</text>
            </g>
          </g>
        </g>

        <g class="nodes">
          <g v-for="node in layout.nodes" :key="node.id">
            <rect
              :x="node.x" :y="node.y" :width="NODE_W" :height="NODE_H" rx="10"
              :fill="colorOf(node.kind).fill" :stroke="colorOf(node.kind).stroke" stroke-width="1.4"
            />
            <text :x="node.x + NODE_W / 2" :y="node.y + NODE_H / 2 + 5" text-anchor="middle" class="node-label" :fill="colorOf(node.kind).text">
              {{ node.label }}
            </text>
          </g>
        </g>
      </svg>
    </div>
    <div class="legend">
      <span v-for="item in legend" :key="item.kind" class="legend-item">
        <i :style="{ background: colorOf(item.kind).fill, borderColor: colorOf(item.kind).stroke }"></i>{{ item.text }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.graph-card { overflow: hidden; }
.graph-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid #eef0f4;
}
.graph-scroll { overflow-x: auto; padding: 12px 14px 2px; background: #fcfdff; }
svg { display: block; max-width: none; }
.node-label { font-size: 12.5px; font-weight: 600; }
.edge-label { font-size: 10.5px; fill: #64748b; }
.legend {
  display: flex; flex-wrap: wrap; gap: 16px;
  padding: 10px 18px 14px; border-top: 1px solid #eef0f4;
}
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: #6b7280; }
.legend-item i { width: 11px; height: 11px; border-radius: 3px; border: 1px solid; display: inline-block; }
</style>
