<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createOrder, listOrders, listProducts, refund } from '../api/client'
import type { Order, Product } from '../types'

const orders = ref<Order[]>([])
const products = ref<Product[]>([])
const selectedProduct = ref('')
const quantity = ref(1)
const created = ref<Order | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')
const refundTarget = ref<Order | null>(null)
const refundReason = ref('用户申请')
const refunding = ref(false)

const statusClass: Record<string, string> = {
  created: 'badge-blue',
  shipped: 'badge-purple',
  completed: 'badge-green',
  refunding: 'badge-amber',
  refunded: 'badge-red',
  cancelled: 'badge-red',
}

const statusText: Record<string, string> = {
  created: '已创建',
  shipped: '已发货',
  completed: '已完成',
  refunding: '退款中',
  refunded: '已退款',
  cancelled: '已取消',
}

function badgeClass(status: string): string {
  return statusClass[status] || 'badge'
}

function badgeText(status: string): string {
  return statusText[status] || status
}

function productName(id: string): string {
  return products.value.find((item) => item.id === id)?.name || id
}

function money(value: number): string {
  return value.toFixed(2)
}

function time(value: string): string {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\+.*$/, '')
}

async function loadOrders(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    orders.value = await listOrders()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '订单加载失败'
  } finally {
    loading.value = false
  }
}

async function submitOrder(): Promise<void> {
  if (!selectedProduct.value || quantity.value < 1) return
  submitting.value = true
  error.value = ''
  try {
    created.value = await createOrder([{ product_id: selectedProduct.value, quantity: Number(quantity.value) }])
    await loadOrders()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '下单失败'
    created.value = null
  } finally {
    submitting.value = false
  }
}

function openRefund(order: Order): void {
  refundTarget.value = order
  refundReason.value = '用户申请'
}

async function confirmRefund(): Promise<void> {
  if (!refundTarget.value) return
  refunding.value = true
  error.value = ''
  try {
    const result = await refund(refundTarget.value.id, refundReason.value.trim() || '用户申请')
    error.value = `订单 ${result.order_id} 退款申请已提交，当前状态：${badgeText(result.status)}`
    refundTarget.value = null
    await loadOrders()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '退款申请失败'
  } finally {
    refunding.value = false
  }
}

onMounted(async () => {
  await loadOrders()
  try {
    products.value = await listProducts()
  } catch {
    // Products are optional for the create form; the list still remains usable.
  }
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="section-title">订单管理</h2>
        <p class="small muted">查看订单、创建新订单并发起退款申请</p>
      </div>
      <button class="btn" type="button" :disabled="loading" @click="loadOrders">刷新列表</button>
    </div>

    <div v-if="error" class="notice error">{{ error }}</div>

    <section class="card form-card">
      <h3 class="block-title">新建订单</h3>
      <form class="order-form" @submit.prevent="submitOrder">
        <label class="field">
          <span class="small muted">选择商品</span>
          <select v-model="selectedProduct" class="select" required>
            <option value="" disabled>请选择商品</option>
            <option v-for="product in products" :key="product.id" :value="product.id">
              {{ product.name }} - ¥{{ money(product.price) }}
            </option>
          </select>
        </label>
        <label class="field quantity-field">
          <span class="small muted">数量</span>
          <input v-model.number="quantity" class="input" type="number" min="1" max="99" />
        </label>
        <button class="btn btn-primary submit-btn" type="submit" :disabled="submitting || !selectedProduct">
          {{ submitting ? '提交中...' : '创建订单' }}
        </button>
      </form>
      <div v-if="created" class="result-panel">
        <span class="badge badge-green">创建成功</span>
        <span class="mono small">订单号 {{ created.id }}</span>
        <span class="small muted">金额 ¥{{ money(created.total) }}</span>
        <span class="badge" :class="badgeClass(created.status)">{{ badgeText(created.status) }}</span>
      </div>
    </section>

    <section class="card table-card">
      <div class="table-head">
        <h3 class="block-title">订单列表</h3>
        <span class="badge">{{ orders.length }} 条记录</span>
      </div>
      <div v-if="loading" class="empty-state">正在加载订单...</div>
      <div v-else-if="orders.length === 0" class="empty-state">暂无订单</div>
      <div v-else class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>客户</th>
              <th>商品明细</th>
              <th>金额</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in orders" :key="order.id">
              <td class="mono small">{{ order.id }}</td>
              <td class="mono small">{{ order.customer_id }}</td>
              <td>
                <div v-for="item in order.items" :key="item.product_id" class="item-line">
                  {{ productName(item.product_id) }} x{{ item.quantity }}
                  <span class="muted small">@ ¥{{ money(item.unit_price) }}</span>
                </div>
              </td>
              <td class="amount">¥{{ money(order.total) }}</td>
              <td><span class="badge" :class="badgeClass(order.status)">{{ badgeText(order.status) }}</span></td>
              <td class="small muted">{{ time(order.created_at) }}</td>
              <td>
                <button
                  class="btn btn-sm btn-danger"
                  type="button"
                  :disabled="order.status === 'refunded' || order.status === 'cancelled'"
                  @click="openRefund(order)"
                >
                  申请退款
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="refundTarget" class="modal-mask" @click.self="refundTarget = null">
      <div class="card modal">
        <h3 class="block-title">申请退款</h3>
        <p class="small muted">订单 {{ refundTarget.id }} - 金额 ¥{{ money(refundTarget.total) }}</p>
        <label class="field">
          <span class="small muted">退款原因</span>
          <input v-model="refundReason" class="input" type="text" placeholder="请输入退款原因" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="refundTarget = null">取消</button>
          <button class="btn btn-primary" type="button" :disabled="refunding" @click="confirmRefund">
            {{ refunding ? '提交中...' : '确认申请' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1180px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 18px; }
.page-head p { margin-top: 4px; }
.notice { padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; font-size: 13px; }
.notice.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.form-card { padding: 16px 18px; margin-bottom: 18px; }
.block-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; }
.order-form { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 180px; }
.quantity-field { flex: 0 0 120px; }
.submit-btn { min-width: 116px; }
.result-panel { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 14px; padding: 10px 12px; background: #f6fbf8; border-radius: 8px; border: 1px solid #dcefe3; }
.table-card { overflow: hidden; }
.table-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px 0; }
.table-scroll { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; font-weight: 500; color: #6b7280; background: #fafbfd; padding: 11px 14px; border-bottom: 1px solid #eef0f4; white-space: nowrap; }
.data-table td { padding: 12px 14px; border-bottom: 1px solid #f1f3f6; vertical-align: top; }
.data-table tr:last-child td { border-bottom: none; }
.item-line { white-space: nowrap; }
.amount { font-weight: 600; color: #b45309; white-space: nowrap; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.32); display: grid; place-items: center; z-index: 50; }
.modal { width: 380px; max-width: calc(100vw - 32px); padding: 20px; }
.modal p { margin-bottom: 14px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
</style>
