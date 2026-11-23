package com.example.ecom.repository;

import com.example.ecom.domain.User;
import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, String> {
    /** 前端登录框传的是显示名（如“张三”），需与用户 ID（U001）同时支持。 */
    java.util.Optional<User> findByName(String name);
}
