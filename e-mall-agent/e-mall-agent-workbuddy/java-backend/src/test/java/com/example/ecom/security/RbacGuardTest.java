package com.example.ecom.security;

import com.example.ecom.domain.User;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class RbacGuardTest {

    private final RbacGuard guard = new RbacGuard();

    @Test
    void permissionsByRole() {
        assertTrue(guard.permissionsFor("customer").contains("order:create"));
        assertFalse(guard.permissionsFor("customer").contains("audit:read"));
        assertTrue(guard.permissionsFor("admin").contains("audit:read"));
        assertTrue(guard.permissionsFor(null).contains("product:read"));
    }

    @Test
    void requireThrowsForGuest() {
        assertThrows(ApiException.class,
                () -> guard.require(new User("anonymous", "访客", "guest"), "chat:use"));
        assertDoesNotThrow(() -> guard.require(new User("u-1", "客户", "customer"), "chat:use"));
    }

    @Test
    void toolWhitelistBlocksRefundForService() {
        assertTrue(guard.toolAllowed("customer", "searchProducts"));
        assertTrue(guard.toolAllowed("customer", "requestRefund"));
        assertFalse(guard.toolAllowed("guest", "createOrder"));
        assertFalse(guard.toolAllowed("service", "createOrder"));
    }

    @Test
    void customerScopeIsolation() {
        User customer = new User("u-1", "客户", "customer");
        assertThrows(ApiException.class, () -> guard.requireCustomerScope(customer, "u-2"));
        assertDoesNotThrow(() -> guard.requireCustomerScope(customer, "u-1"));
        assertDoesNotThrow(() -> guard.requireCustomerScope(
                new User("s-1", "客服", "service"), "u-2"));
    }

    @Test
    void permissionListIsOrderedAndImmutable() {
        List<String> permissions = guard.permissionsFor("admin");
        assertThrows(UnsupportedOperationException.class, () -> permissions.add("x"));
    }
}
