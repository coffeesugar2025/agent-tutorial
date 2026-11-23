package com.xingtu.agent.api;

import com.xingtu.agent.api.dto.OrderDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.common.PageResult;
import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.infra.repo.LogisticsRepository;
import com.xingtu.agent.infra.repo.OrderRepository;
import com.xingtu.agent.security.PiiMasker;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 订单与物流接口（docs/03-API契约.md 第 4 节）。
 * 所有查询都限定当前登录用户，避免横向越权。
 */
@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {

    private static final int MAX_PAGE_SIZE = 100;

    private final OrderRepository orderRepository;
    private final LogisticsRepository logisticsRepository;
    private final PiiMasker piiMasker;

    public OrderController(OrderRepository orderRepository, LogisticsRepository logisticsRepository,
                           PiiMasker piiMasker) {
        this.orderRepository = orderRepository;
        this.logisticsRepository = logisticsRepository;
        this.piiMasker = piiMasker;
    }

    @GetMapping
    public ApiResponse<PageResult<OrderDtos.OrderVO>> list(
            @RequestParam(value = "status", required = false) String status,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "20") int size) {
        int normalizedPage = PageResult.normalizePage(page);
        int normalizedSize = PageResult.normalizeSize(size, MAX_PAGE_SIZE);
        PageResult<OrderRepository.OrderRow> rows = orderRepository.listByUser(TraceContext.userId(),
                status, normalizedPage, normalizedSize);
        List<OrderDtos.OrderVO> items = new ArrayList<>(rows.items().size());
        for (OrderRepository.OrderRow row : rows.items()) {
            items.add(toVO(row));
        }
        return ApiResponse.ok(PageResult.of(items, rows.total(), normalizedPage, normalizedSize));
    }

    @GetMapping("/{orderNo}")
    public ApiResponse<OrderDtos.OrderVO> detail(@PathVariable("orderNo") String orderNo) {
        return ApiResponse.ok(toVO(requireOwnOrder(orderNo)));
    }

    @GetMapping("/{orderNo}/logistics")
    public ApiResponse<OrderDtos.LogisticsVO> logistics(@PathVariable("orderNo") String orderNo) {
        OrderRepository.OrderRow order = requireOwnOrder(orderNo);
        LogisticsRepository.LogisticsRow row = logisticsRepository.findByOrderId(order.id());
        if (row == null) {
            row = logisticsRepository.findByOrderNo(order.orderNo());
        }
        if (row == null) {
            throw BizException.notFound("暂无物流信息: " + orderNo);
        }
        List<OrderDtos.LogisticsEventVO> events = new ArrayList<>();
        List<Map> rawEvents = JsonUtil.parseList(row.eventsJson(), Map.class);
        for (Map<?, ?> event : rawEvents) {
            events.add(new OrderDtos.LogisticsEventVO(stringValue(event, "time"),
                    stringValue(event, "desc")));
        }
        return ApiResponse.ok(new OrderDtos.LogisticsVO(row.company(), row.trackingNo(), row.status(),
                row.latestEvent(), events));
    }

    private OrderRepository.OrderRow requireOwnOrder(String orderNo) {
        if (orderNo == null || orderNo.isBlank()) {
            throw BizException.validation("orderNo 不能为空");
        }
        OrderRepository.OrderRow row = orderRepository.findByOrderNo(orderNo.trim());
        if (row == null || row.userId() != TraceContext.userId()) {
            throw BizException.notFound("订单不存在: " + orderNo);
        }
        return row;
    }

    private OrderDtos.OrderVO toVO(OrderRepository.OrderRow row) {
        List<OrderDtos.OrderItemVO> items = new ArrayList<>();
        for (OrderRepository.ItemRow item : orderRepository.items(row.id())) {
            items.add(new OrderDtos.OrderItemVO(item.sku(), item.title(), item.price(), item.quantity()));
        }
        return new OrderDtos.OrderVO(row.id(), row.orderNo(), row.status(), row.totalAmount(),
                row.payAmount(), row.receiverName(), piiMasker.maskPhone(row.receiverPhone()),
                JsonUtil.formatTime(row.createdAt()), items);
    }

    private String stringValue(Map<?, ?> map, String key) {
        Object value = map.get(key);
        return value == null ? null : String.valueOf(value);
    }
}
