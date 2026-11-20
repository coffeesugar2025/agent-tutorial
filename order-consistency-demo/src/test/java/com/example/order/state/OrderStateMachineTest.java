package com.example.order.state;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class OrderStateMachineTest {

    private final OrderStateMachine sm = new OrderStateMachine();

    @Test
    void createdCanPayOrCancel() {
        assertDoesNotThrow(() -> sm.assertTransition(OrderStatus.CREATED, OrderStatus.PAID));
        assertDoesNotThrow(() -> sm.assertTransition(OrderStatus.CREATED, OrderStatus.CANCELLED));
    }

    @Test
    void cannotGoBackwards() {
        assertThrows(OrderStateMachine.IllegalStateTransitionException.class,
                () -> sm.assertTransition(OrderStatus.PAID, OrderStatus.CREATED));
    }

    @Test
    void terminalStatesAreTerminal() {
        assertThrows(OrderStateMachine.IllegalStateTransitionException.class,
                () -> sm.assertTransition(OrderStatus.COMPLETED, OrderStatus.PAID));
        assertThrows(OrderStateMachine.IllegalStateTransitionException.class,
                () -> sm.assertTransition(OrderStatus.CANCELLED, OrderStatus.PAID));
    }

    @Test
    void refundPathIsExplicit() {
        assertDoesNotThrow(() -> sm.assertTransition(OrderStatus.PAID, OrderStatus.REFUNDING));
        assertDoesNotThrow(() -> sm.assertTransition(OrderStatus.REFUNDING, OrderStatus.REFUNDED));
        assertThrows(OrderStateMachine.IllegalStateTransitionException.class,
                () -> sm.assertTransition(OrderStatus.PAID, OrderStatus.REFUNDED));
    }
}
