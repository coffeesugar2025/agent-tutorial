package com.example.ecom.service;

import com.example.ecom.observability.Metrics;
import com.example.ecom.repository.AuditLogRepository;
import com.example.ecom.repository.OrderRepository;
import com.example.ecom.repository.ProductRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class WorkflowServiceStateMachineTest {

    private WorkflowService workflow;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        ObjectProvider<RabbitTemplate> rabbit =
                new DefaultListableBeanFactory().getBeanProvider(RabbitTemplate.class);
        workflow = new WorkflowService(mock(OrderRepository.class), mock(ProductRepository.class),
                mock(AuditLogRepository.class), new ObjectMapper(), new Metrics(),
                rabbit, false, 500.0);
    }

    @Test
    void allowsHappyPathTransitions() {
        assertTrue(WorkflowService.canTransition("created", "paid"));
        assertTrue(WorkflowService.canTransition("paid", "shipped"));
        assertTrue(WorkflowService.canTransition("shipped", "delivered"));
    }

    @Test
    void rejectsIllegalTransitions() {
        assertFalse(WorkflowService.canTransition("created", "delivered"));
        assertFalse(WorkflowService.canTransition("delivered", "paid"));
        assertFalse(WorkflowService.canTransition("refunded", "shipped"));
    }

    @Test
    void refundBranchIsAllowedFromPaidAndShipped() {
        assertTrue(WorkflowService.canTransition("paid", "refund_requested"));
        assertTrue(WorkflowService.canTransition("shipped", "refund_requested"));
        assertEquals(2, workflow.nextStates("paid").size());
    }

    @Test
    void parseItemsRejectsMalformedJson() {
        assertThrows(IllegalArgumentException.class, () -> workflow.parseItems("not-json"));
        assertTrue(workflow.parseItems("").isEmpty());
    }
}
