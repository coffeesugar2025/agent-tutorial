package com.xingtu.agent.integration;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：商品 API 测试：MockMvc standaloneSetup + Mockito 仓储，不依赖数据库与 Sprin
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.api.ProductController;
import com.xingtu.agent.common.GlobalExceptionHandler;
import com.xingtu.agent.common.PageResult;
import com.xingtu.agent.infra.repo.ProductRepository;
import com.xingtu.agent.rag.SparseEncoder;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 商品 API 测试：MockMvc standaloneSetup + Mockito 仓储，不依赖数据库与 Spring 上下文。
 */
class ProductApiTest {

    private ProductRepository productRepository;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        productRepository = mock(ProductRepository.class);
        ProductController controller = new ProductController(productRepository, new SparseEncoder());
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    private ProductRepository.ProductRow product() {
        return new ProductRepository.ProductRow(1L, "PH-001", "星图 X1 拍照手机", "旗舰影像", "Apple",
                3L, "手机", new BigDecimal("4999.00"), new BigDecimal("5499.00"), 12,
                new BigDecimal("4.8"), 3200, "https://img.example.com/1.jpg", "{\"color\":\"黑\"}", 1,
                "超强夜景模式");
    }

    @Test
    void listReturnsPagedProducts() throws Exception {
        when(productRepository.search(any(), any(), any(), any(), anyInt(), anyInt()))
                .thenReturn(PageResult.of(List.of(product()), 1L, 1, 20));

        mockMvc.perform(get("/api/v1/products").param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.page").value(1))
                .andExpect(jsonPath("$.data.size").value(20))
                .andExpect(jsonPath("$.data.items[0].sku").value("PH-001"))
                .andExpect(jsonPath("$.data.items[0].price").value(4999.00))
                .andExpect(jsonPath("$.data.items[0].categoryName").value("手机"))
                .andExpect(jsonPath("$.data.items[0].attrs.color").value("黑"));
    }

    @Test
    void detailIncludesDescription() throws Exception {
        when(productRepository.findBySku("PH-001")).thenReturn(product());

        mockMvc.perform(get("/api/v1/products/PH-001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.sku").value("PH-001"))
                .andExpect(jsonPath("$.data.description").value("超强夜景模式"));
    }

    @Test
    void unknownSkuIsNotFound() throws Exception {
        when(productRepository.findBySku("NOPE")).thenReturn(null);

        mockMvc.perform(get("/api/v1/products/NOPE"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(40400));
    }

    @Test
    void searchReturnsHybridStrategyWithScores() throws Exception {
        when(productRepository.fullTextSearch(any(), anyInt())).thenReturn(List.of(product()));

        mockMvc.perform(post("/api/v1/products/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"拍照手机\",\"topK\":3,\"maxPrice\":5000,"
                                + "\"brands\":[\"Apple\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.strategy").value("hybrid"))
                .andExpect(jsonPath("$.data.items[0].sku").value("PH-001"))
                .andExpect(jsonPath("$.data.items[0].score").isNumber())
                .andExpect(jsonPath("$.data.items[0].reason").isNotEmpty());
    }

    @Test
    void searchRejectsBlankQuery() throws Exception {
        mockMvc.perform(post("/api/v1/products/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"  \"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(40001));
    }
}
