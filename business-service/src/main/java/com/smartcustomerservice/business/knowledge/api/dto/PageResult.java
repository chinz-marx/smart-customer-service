package com.smartcustomerservice.business.knowledge.api.dto;

import java.util.List;

/** 前端表格统一使用的分页结构。 */
public record PageResult<T>(List<T> records, long total, long page, long size) {
}
