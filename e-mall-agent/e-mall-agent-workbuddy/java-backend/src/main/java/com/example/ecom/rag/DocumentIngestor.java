package com.example.ecom.rag;

import dev.langchain4j.data.document.Document;
import dev.langchain4j.data.document.splitter.DocumentSplitters;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.model.embedding.EmbeddingModel;
import dev.langchain4j.store.embedding.EmbeddingStore;
import dev.langchain4j.store.embedding.EmbeddingStoreIngestor;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * RAG 文档入库：Milvus（配置且 Key 可用时）或进程内分块（默认回退）。
 * 种子知识覆盖退货/物流/支付/售后等常见客服问题。
 */
@Component
public class DocumentIngestor {

    public record Chunk(String text, String source) {}

    private final ObjectProvider<EmbeddingStore<TextSegment>> embeddingStore;
    private final ObjectProvider<EmbeddingModel> embeddingModel;

    private final List<Chunk> chunks = new ArrayList<>();
    private volatile boolean vectorIngest = false;

    public DocumentIngestor(ObjectProvider<EmbeddingStore<TextSegment>> embeddingStore,
                            ObjectProvider<EmbeddingModel> embeddingModel) {
        this.embeddingStore = embeddingStore;
        this.embeddingModel = embeddingModel;
    }

    @PostConstruct
    public void seed() {
        ingest("退货政策", "我们的退货政策：签收后 7 天内可无理由退货，商品需保持完好；"
                + "退款在仓库验收后 1-3 个工作日原路退回。超过 500 元的退款需要人工审批。");
        ingest("物流配送", "物流配送：默认顺丰快递，工作日 24 小时内发出；"
                + "偏远地区 3-5 天送达。订单状态依次为 created、paid、shipped、delivered。");
        ingest("支付方式", "支付方式：支持微信、支付宝与银行卡；下单后 30 分钟内未支付将自动取消。");
        ingest("售后服务", "售后服务：质保一年，非人为损坏免费维修；客服可在工作时间内协助退款与改地址。");
        ingest("商品分类", "商品分类：数码（耳机、键盘、笔记本）、家居（咖啡机）、服饰（围巾）。"
                + "可用 /api/products?category= 按分类筛选。");
        ingest("隐私安全", "隐私安全：用户输入会经过注入扫描，工具调用受 RBAC 白名单限制，敏感操作写入审计日志。");
    }

    public void ingest(String source, String text) {
        chunks.add(new Chunk(text, source));
        EmbeddingStore<TextSegment> store = embeddingStore.getIfAvailable();
        EmbeddingModel model = embeddingModel.getIfAvailable();
        if (store != null && model != null) {
            try {
                EmbeddingStoreIngestor.builder()
                        .documentSplitter(DocumentSplitters.recursive(800, 100))
                        .embeddingModel(model)
                        .embeddingStore(store)
                        .build()
                        .ingest(Document.from(text));
                vectorIngest = true;
            } catch (RuntimeException ignored) {
                vectorIngest = false;
            }
        }
    }

    public List<Chunk> chunks() {
        return List.copyOf(chunks);
    }

    public boolean vectorIngest() {
        return vectorIngest;
    }
}
