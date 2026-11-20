package com.example.order.web;

import com.example.order.model.CreateOrderRequest;
import com.example.order.model.OrderResponse;
import com.example.order.service.OrderService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderService service;

    public OrderController(OrderService service) {
        this.service = service;
    }

    @PostMapping
    public OrderResponse create(@RequestHeader("Idempotency-Key") String key,
                                @Valid @RequestBody CreateOrderRequest req) {
        return service.create(key, req);
    }

    @PostMapping("/{id}/pay")
    public OrderResponse pay(@PathVariable("id") Long id) {
        return service.pay(id);
    }
}
