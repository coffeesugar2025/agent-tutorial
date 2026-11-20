package com.example.order.model;

public record OrderCreatedEvent(Long orderId, Long skuId, int qty) {
}
