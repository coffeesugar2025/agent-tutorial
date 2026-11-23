import type { PageResult, ProductQuery, ProductSearchRequest, ProductSearchResult, ProductVO } from '@/types'
import { compactParams, get, post } from './http'

export function listProducts(query: ProductQuery): Promise<PageResult<ProductVO>> {
  return get<PageResult<ProductVO>>(
    '/products',
    compactParams({
      keyword: query.keyword,
      categoryId: query.categoryId,
      minPrice: query.minPrice,
      maxPrice: query.maxPrice,
      page: query.page ?? 1,
      size: query.size ?? 20,
    }),
  )
}

export function getProduct(sku: string): Promise<ProductVO> {
  return get<ProductVO>(`/products/${encodeURIComponent(sku)}`)
}

export function searchProducts(payload: ProductSearchRequest): Promise<ProductSearchResult> {
  return post<ProductSearchResult>('/products/search', payload)
}
