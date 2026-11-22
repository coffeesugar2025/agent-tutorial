<script setup lang="ts">
import type { AgentCard } from '../types'
import { formatMoney } from '../api/sse'

defineProps<{ cards: AgentCard[] }>()

function isWide(card: AgentCard): boolean {
  return card.type === 'order' || card.type === 'policy' || card.type === 'price'
}
</script>

<template>
  <div class="card-grid" v-if="cards.length">
    <div v-for="(c, i) in cards" :key="`${c.type}-${c.sku ?? c.order_id ?? c.code ?? i}`"
         class="info-card" :class="{ wide: isWide(c) }">

      <!-- 商品卡 -->
      <template v-if="c.type === 'product'">
        <div class="card-head">
          <div>
            <div class="card-title">{{ c.title }}</div>
            <div class="card-sub">{{ c.subtitle }} · {{ c.sku }}</div>
          </div>
          <div class="card-price">{{ formatMoney(c.price) }}</div>
        </div>
        <div class="tag-row">
          <span class="tag" v-for="t in c.tags ?? []" :key="t">{{ t }}</span>
        </div>
        <div class="card-foot">
          <span>评分 {{ c.rating ?? '—' }}</span>
          <span :class="['pill', c.in_stock ? 'ok' : 'no']">
            {{ c.in_stock ? `有货 ${c.stock} 件` : '暂时缺货' }}
          </span>
        </div>
      </template>

      <!-- 订单卡 -->
      <template v-else-if="c.type === 'order'">
        <div class="card-head">
          <div>
            <div class="card-title">订单 {{ c.order_id }}</div>
            <div class="card-sub">{{ c.created_at }} · 共 {{ (c.items ?? []).length }} 件商品</div>
          </div>
          <span class="pill info">{{ c.status }}</span>
        </div>
        <div class="tag-row" v-if="c.items?.length">
          <span class="tag" v-for="item in c.items" :key="item.sku">{{ item.name }} ×{{ item.qty }}</span>
        </div>
        <div class="card-foot">
          <span>实付 {{ formatMoney(c.total) }}</span>
          <span>物流：{{ c.node || '暂无节点' }}</span>
        </div>
      </template>

      <!-- 到手价卡 -->
      <template v-else-if="c.type === 'price'">
        <div class="card-head">
          <div>
            <div class="card-title">{{ c.title }}</div>
            <div class="card-sub">{{ c.sku }} · 数量 {{ c.quantity }}</div>
          </div>
          <span class="pill ok">已核算</span>
        </div>
        <div class="price-line"><span>商品小计</span><span>{{ formatMoney(c.subtotal) }}</span></div>
        <div class="price-line" v-for="cp in c.coupons ?? []" :key="cp.code">
          <span>{{ cp.title }}（{{ cp.code }}）</span><span>- {{ formatMoney(cp.amount) }}</span>
        </div>
        <div class="price-line"><span>优惠合计</span><span>- {{ formatMoney(c.discount) }}</span></div>
        <div class="price-line total"><span>到手价</span><span>{{ formatMoney(c.payable, c.currency) }}</span></div>
      </template>

      <!-- 优惠券卡 -->
      <template v-else-if="c.type === 'coupon'">
        <div class="card-head">
          <div class="card-title">{{ c.title }}</div>
          <span class="pill ok">{{ c.code }}</span>
        </div>
        <div class="card-sub">满 {{ formatMoney(c.threshold) }} 可用</div>
      </template>

      <!-- 政策卡 -->
      <template v-else-if="c.type === 'policy'">
        <div class="card-head">
          <div class="card-title">{{ c.topic }}政策</div>
          <span class="pill info">官方规则</span>
        </div>
        <div class="card-sub" style="margin-top: 8px; line-height: 1.7; font-size: 12px">{{ c.content }}</div>
      </template>

      <!-- 售后资格卡 -->
      <template v-else-if="c.type === 'after_sale'">
        <div class="card-head">
          <div class="card-title">退货资格判定</div>
          <span :class="['pill', c.eligible ? 'ok' : 'no']">{{ c.eligible ? '符合条件' : '不符合' }}</span>
        </div>
        <div class="card-sub" style="margin-top: 8px">{{ c.reason }}</div>
        <div class="card-foot"><span>剩余天数</span><span>{{ c.days_left ?? 0 }} 天</span></div>
      </template>

      <!-- 库存卡 -->
      <template v-else-if="c.type === 'inventory'">
        <div class="card-title">{{ c.title }}</div>
        <div class="card-sub">{{ c.sku }}</div>
        <div class="card-foot"><span>可用库存</span><span>{{ c.stock }} 件</span></div>
      </template>
    </div>
  </div>
</template>
