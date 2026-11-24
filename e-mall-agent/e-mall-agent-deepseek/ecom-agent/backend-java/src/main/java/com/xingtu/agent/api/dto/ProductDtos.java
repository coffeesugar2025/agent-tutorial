package com.xingtu.agent.api.dto;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  （支撑）
// 职责：商品相关 DTO（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.fasterxml.jackson.annotation.JsonInclude;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 商品相关 DTO（docs/03-API契约.md 第 3 节）。
 */
public final class ProductDtos {

    private ProductDtos() {
    }

    /**
     * 商品视图：列表接口不返回 description（NON_NULL 时省略），详情接口返回。
     */
    public record ProductVO(long id, String sku, String title, String subtitle, String brand,
                            long categoryId, String categoryName, BigDecimal price,
                            BigDecimal originalPrice, int stock, BigDecimal rating, int sales,
                            String imageUrl, Map<String, Object> attrs, int status,
                            @JsonInclude(JsonInclude.Include.NON_NULL) String description) {
    }

    /** POST /api/v1/products/search 请求体。 */
    public record ProductSearchReq(String query, Integer topK, BigDecimal maxPrice, List<String> brands) {
    }

    /** 检索结果项。 */
    public record ProductSearchItemVO(String sku, String title, BigDecimal price, double score,
                                      String reason) {
    }

    /** 检索结果。 */
    public record ProductSearchVO(List<ProductSearchItemVO> items, String strategy) {
    }
}
