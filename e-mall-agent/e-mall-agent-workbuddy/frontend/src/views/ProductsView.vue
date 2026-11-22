<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listProducts } from '../api/client'
import type { Product } from '../types'

const router = useRouter()
const products = ref<Product[]>([])
const query = ref('')
const loading = ref(false)
const error = ref('')
const searched = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    products.value = await listProducts(query.value.trim())
    searched.value = query.value.trim()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '商品加载失败'
    products.value = []
  } finally {
    loading.value = false
  }
}

function consult(product: Product): void {
  void router.push({
    path: '/chat',
    query: { q: `请介绍一下「${product.name}」，并给出购买建议` },
  })
}

function priceText(value: number): string {
  return value.toFixed(2)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="section-title">商品目录</h2>
        <p class="small muted">浏览在售商品，或让智能助手帮你比较与推荐</p>
      </div>
      <form class="search-box" @submit.prevent="load">
        <input v-model="query" class="input" type="search" placeholder="搜索商品名称、标签或分类" />
        <button class="btn btn-primary" type="submit" :disabled="loading">{{ loading ? '查询中' : '搜索' }}</button>
      </form>
    </div>

    <div v-if="error" class="notice error">{{ error }}</div>
    <div v-if="searched" class="small muted result-hint">搜索「{{ searched }}」的结果</div>

    <div v-if="loading" class="empty-state card">正在加载商品...</div>
    <div v-else-if="products.length === 0 && !error" class="empty-state card">没有找到匹配的商品</div>

    <div v-else class="product-grid">
      <article v-for="product in products" :key="product.id" class="card product-card">
        <div class="product-top">
          <div class="product-icon">{{ product.name.slice(0, 1) }}</div>
          <span class="badge badge-blue">{{ product.category }}</span>
        </div>
        <h3 class="product-name">{{ product.name }}</h3>
        <p class="product-desc">{{ product.description || '暂无商品描述' }}</p>
        <div class="tags">
          <span v-for="tag in product.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <div class="product-meta">
          <div class="price">¥ {{ priceText(product.price) }}</div>
          <span class="badge" :class="product.stock > 0 ? 'badge-green' : 'badge-red'">
            {{ product.stock > 0 ? `库存 ${product.stock}` : '暂时缺货' }}
          </span>
        </div>
        <button class="btn consult-btn" type="button" @click="consult(product)">向助手咨询</button>
      </article>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1180px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.page-head p { margin-top: 4px; }
.search-box { display: flex; gap: 8px; width: 360px; max-width: 100%; }
.result-hint { margin-bottom: 12px; }
.notice { padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; font-size: 13px; }
.notice.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }

.product-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; }
.product-card { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.product-top { display: flex; align-items: center; justify-content: space-between; }
.product-icon {
  width: 38px; height: 38px; border-radius: 9px; display: grid; place-items: center;
  background: #eaf1ff; color: #1d4ed8; font-size: 17px; font-weight: 650;
}
.product-name { font-size: 15px; font-weight: 600; }
.product-desc { font-size: 12px; color: #6b7280; min-height: 36px; line-height: 1.5; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; min-height: 20px; }
.tag { font-size: 11px; padding: 2px 7px; border-radius: 4px; background: #f3f5f9; color: #64748b; }
.product-meta { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 6px; border-top: 1px solid #eef0f4; }
.price { font-size: 18px; font-weight: 650; color: #d97706; }
.consult-btn { width: 100%; border-color: #bfd4f7; color: #1d4ed8; background: #f5f9ff; }
.consult-btn:hover { background: #eaf1ff; }
</style>
