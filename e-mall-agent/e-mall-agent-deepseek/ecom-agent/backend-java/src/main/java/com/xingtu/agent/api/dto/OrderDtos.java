package com.xingtu.agent.api.dto;

import java.math.BigDecimal;
import java.util.List;

/**
 * 订单与物流 DTO（docs/03-API契约.md 第 4 节）。
 */
public final class OrderDtos {

    private OrderDtos() {
    }

    /** 订单明细项。 */
    public record OrderItemVO(String sku, String title, BigDecimal price, int quantity) {
    }

    /** 订单视图（receiverPhone 已脱敏）。 */
    public record OrderVO(long id, String orderNo, String status, BigDecimal totalAmount,
                          BigDecimal payAmount, String receiverName, String receiverPhone,
                          String createdAt, List<OrderItemVO> items) {
    }

    /** 物流轨迹事件。 */
    public record LogisticsEventVO(String time, String desc) {
    }

    /** 物流视图。 */
    public record LogisticsVO(String company, String trackingNo, String status, String latestEvent,
                              List<LogisticsEventVO> events) {
    }
}
