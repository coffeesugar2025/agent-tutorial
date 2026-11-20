package com.example.order.model;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

public record CreateOrderRequest(@NotNull Long skuId, @Min(1) int qty) {
}
