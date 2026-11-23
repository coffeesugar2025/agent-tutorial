package com.example.ecom.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/** 审计日志：记录鉴权决策、工具调用、退款审批等敏感操作。 */
@Entity
@Table(name = "audit_logs")
public class AuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "actor", nullable = false)
    private String actor;

    @Column(name = "action", nullable = false)
    private String action;

    @Column(name = "target")
    private String target = "";

    /** allow / deny */
    @Column(name = "decision")
    private String decision = "allow";

    @Column(name = "detail", length = 512)
    private String detail = "";

    @Column(name = "created_at")
    private String createdAt = Instant.now().toString();

    public AuditLog() {
    }

    public AuditLog(String actor, String action, String target, String decision, String detail) {
        this.actor = actor;
        this.action = action;
        this.target = target;
        this.decision = decision;
        this.detail = detail == null ? "" : detail;
    }

    public Long getId() { return id; }
    public String getActor() { return actor; }
    public String getAction() { return action; }
    public String getTarget() { return target; }
    public String getDecision() { return decision; }
    public String getDetail() { return detail; }
    public String getCreatedAt() { return createdAt; }
}
