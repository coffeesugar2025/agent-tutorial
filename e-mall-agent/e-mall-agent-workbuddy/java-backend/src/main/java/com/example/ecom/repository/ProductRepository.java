package com.example.ecom.repository;

import com.example.ecom.domain.Product;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface ProductRepository extends JpaRepository<Product, String> {

    List<Product> findByCategory(String category);

    @Query("select p from Product p where lower(p.name) like lower(concat('%', :q, '%')) "
            + "or lower(p.description) like lower(concat('%', :q, '%')) "
            + "or lower(p.tags) like lower(concat('%', :q, '%'))")
    List<Product> search(@Param("q") String q);
}
