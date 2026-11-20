package com.example.order.state;

import org.springframework.stereotype.Component;

import java.util.EnumMap;
import java.util.EnumSet;

/**
 * 轻量状态机：只管「能不能转」。
 * 并发下的「别越过去」由 OrderService 里 WHERE status=? 的 CAS 更新兜底，两层缺一不可。
 */
@Component
public class OrderStateMachine {

    private static final EnumMap<OrderStatus, EnumSet<OrderStatus>> ALLOWED =
            new EnumMap<>(OrderStatus.class);

    static {
        ALLOWED.put(OrderStatus.CREATED,   EnumSet.of(OrderStatus.PAID, OrderStatus.CANCELLED));
        ALLOWED.put(OrderStatus.PAID,      EnumSet.of(OrderStatus.SHIPPED, OrderStatus.REFUNDING));
        ALLOWED.put(OrderStatus.SHIPPED,   EnumSet.of(OrderStatus.COMPLETED));
        ALLOWED.put(OrderStatus.REFUNDING, EnumSet.of(OrderStatus.REFUNDED));
        for (OrderStatus s : OrderStatus.values()) {
            ALLOWED.putIfAbsent(s, EnumSet.noneOf(OrderStatus.class));
        }
    }

    public void assertTransition(OrderStatus from, OrderStatus to) {
        if (!ALLOWED.getOrDefault(from, EnumSet.noneOf(OrderStatus.class)).contains(to)) {
            throw new IllegalStateTransitionException(from, to);
        }
    }

    public static class IllegalStateTransitionException extends RuntimeException {
        public IllegalStateTransitionException(OrderStatus from, OrderStatus to) {
            super("illegal transition: " + from + " -> " + to);
        }
    }
}
