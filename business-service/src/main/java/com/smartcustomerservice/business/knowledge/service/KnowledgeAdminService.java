package com.smartcustomerservice.business.knowledge.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeChunkItem;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeDetail;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeListItem;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeSaveRequest;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeApproval;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCategory;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeChunk;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeQuestion;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeApprovalMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeCategoryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeChunkMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQueryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQuestionMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/** 知识新增、修改、停用都只提交审批，不会直接覆盖线上版本。 */
@Service
@RequiredArgsConstructor
public class KnowledgeAdminService {
    private final KnowledgeMapper knowledgeMapper;
    private final KnowledgeVersionMapper versionMapper;
    private final KnowledgeCategoryMapper categoryMapper;
    private final KnowledgeApprovalMapper approvalMapper;
    private final KnowledgeQueryMapper queryMapper;
    private final KnowledgeChunkMapper chunkMapper;
    private final KnowledgeQuestionMapper questionMapper;

    @Transactional(readOnly = true)
    public List<KnowledgeCategory> listCategories() {
        return categoryMapper.selectList(Wrappers.<KnowledgeCategory>lambdaQuery()
                .eq(KnowledgeCategory::getStatus, 1)
                .orderByAsc(KnowledgeCategory::getSortOrder));
    }

    @Transactional(readOnly = true)
    public PageResult<KnowledgeListItem> list(
            long page, long size, String keyword, Long categoryId, String view) {
        long safePage = Math.max(page, 1);
        long safeSize = Math.min(Math.max(size, 1), 100);
        String safeView = normalizeView(view);
        String safeKeyword = StringUtils.trimToNull(keyword);
        long offset = (safePage - 1) * safeSize;
        return new PageResult<>(
                queryMapper.selectPage(safeKeyword, categoryId, safeView, safeSize, offset),
                queryMapper.countPage(safeKeyword, categoryId, safeView),
                safePage,
                safeSize);
    }

    @Transactional(readOnly = true)
    public KnowledgeDetail detail(long knowledgeId) {
        Knowledge knowledge = requireKnowledge(knowledgeId);
        KnowledgeCategory category = categoryMapper.selectById(knowledge.getCategoryId());
        KnowledgeVersion current = knowledge.getCurrentVersionId() == null
                ? null : versionMapper.selectById(knowledge.getCurrentVersionId());
        KnowledgeVersion pending = knowledge.getPendingVersionId() == null
                ? null : versionMapper.selectById(knowledge.getPendingVersionId());
        KnowledgeApproval latest = approvalMapper.selectOne(
                Wrappers.<KnowledgeApproval>lambdaQuery()
                        .eq(KnowledgeApproval::getKnowledgeId, knowledgeId)
                        .orderByDesc(KnowledgeApproval::getId)
                        .last("LIMIT 1"));
        KnowledgeVersion visible = pending != null ? pending : current;
        List<KnowledgeChunkItem> chunks = visible == null
                ? List.of() : loadChunks(visible.getId());
        return new KnowledgeDetail(
                knowledge,
                category == null ? "" : category.getCategoryName(),
                current,
                pending,
                latest,
                chunks);
    }

    @Transactional
    public KnowledgeDetail create(KnowledgeSaveRequest request, String operatorId) {
        validateRequest(request);
        requireCategory(request.getCategoryId());

        Knowledge knowledge = new Knowledge();
        knowledge.setKnowledgeCode("KB-" + compactUuid());
        knowledge.setCategoryId(request.getCategoryId());
        knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_INACTIVE);
        knowledge.setCreatedBy(operatorId);
        knowledge.setUpdatedBy(operatorId);
        knowledge.setLockVersion(0);
        knowledgeMapper.insert(knowledge);

        KnowledgeVersion version = buildVersion(
                knowledge.getId(), 1, request, operatorId, KnowledgeCodes.VERSION_PENDING);
        versionMapper.insert(version);
        saveDrafts(knowledge.getId(), version.getId(), request.getChunks());
        knowledge.setPendingVersionId(version.getId());
        knowledgeMapper.updateById(knowledge);
        createApproval(knowledge, version, KnowledgeCodes.ACTION_CREATE, request, operatorId);
        return detail(knowledge.getId());
    }

    @Transactional
    public KnowledgeDetail update(long knowledgeId, KnowledgeSaveRequest request, String operatorId) {
        validateRequest(request);
        Knowledge knowledge = requireKnowledge(knowledgeId);
        if (!knowledge.getCategoryId().equals(request.getCategoryId())) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }

        KnowledgeVersion version;
        if (knowledge.getPendingVersionId() != null) {
            version = requireVersion(knowledge.getPendingVersionId());
            if (!Integer.valueOf(KnowledgeCodes.VERSION_DRAFT)
                    .equals(version.getVersionStatus())) {
                throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
            }
            applyEditableFields(version, request, operatorId);
            version.setVersionStatus(KnowledgeCodes.VERSION_PENDING);
            versionMapper.updateById(version);
            replaceDrafts(knowledge.getId(), version.getId(), request.getChunks());
        } else {
            version = buildVersion(
                    knowledgeId, nextVersionNo(knowledgeId), request, operatorId,
                    KnowledgeCodes.VERSION_PENDING);
            versionMapper.insert(version);
            saveDrafts(knowledge.getId(), version.getId(), request.getChunks());
            knowledge.setPendingVersionId(version.getId());
        }
        knowledge.setUpdatedBy(operatorId);
        knowledgeMapper.updateById(knowledge);
        createApproval(knowledge, version, KnowledgeCodes.ACTION_UPDATE, request, operatorId);
        return detail(knowledgeId);
    }

    /** 保存编辑草稿；草稿不会创建审批单、发布任务或覆盖当前线上版本。 */
    @Transactional
    public KnowledgeDetail saveDraft(
            long knowledgeId, KnowledgeSaveRequest request, String operatorId) {
        validateRequest(request);
        Knowledge knowledge = requireKnowledge(knowledgeId);
        if (!knowledge.getCategoryId().equals(request.getCategoryId())) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }

        KnowledgeVersion version;
        if (knowledge.getPendingVersionId() == null) {
            version = buildVersion(
                    knowledgeId, nextVersionNo(knowledgeId), request, operatorId,
                    KnowledgeCodes.VERSION_DRAFT);
            versionMapper.insert(version);
            saveDrafts(knowledgeId, version.getId(), request.getChunks());
            knowledge.setPendingVersionId(version.getId());
        } else {
            version = requireVersion(knowledge.getPendingVersionId());
            if (!Integer.valueOf(KnowledgeCodes.VERSION_DRAFT)
                    .equals(version.getVersionStatus())) {
                throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
            }
            applyEditableFields(version, request, operatorId);
            versionMapper.updateById(version);
            replaceDrafts(knowledgeId, version.getId(), request.getChunks());
        }
        knowledge.setUpdatedBy(operatorId);
        knowledgeMapper.updateById(knowledge);
        return detail(knowledgeId);
    }

    @Transactional
    public KnowledgeDetail requestDisable(long knowledgeId, String operatorId) {
        Knowledge knowledge = requireKnowledge(knowledgeId);
        requireNoPendingVersion(knowledge);
        if (knowledge.getCurrentVersionId() == null
                || !Integer.valueOf(KnowledgeCodes.KNOWLEDGE_ACTIVE).equals(knowledge.getStatus())) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        KnowledgeVersion current = versionMapper.selectById(knowledge.getCurrentVersionId());
        KnowledgeSaveRequest request = new KnowledgeSaveRequest();
        request.setApplicationReason("申请停用当前知识");
        createApproval(knowledge, current, KnowledgeCodes.ACTION_DISABLE, request, operatorId);
        // 停用没有新内容版本，但挂起指针可以阻止同时提交其他修改。
        knowledge.setPendingVersionId(current.getId());
        knowledge.setUpdatedBy(operatorId);
        knowledgeMapper.updateById(knowledge);
        return detail(knowledgeId);
    }

    private KnowledgeVersion buildVersion(
            Long knowledgeId, int versionNo, KnowledgeSaveRequest request, String operatorId,
            int versionStatus) {
        KnowledgeVersion version = new KnowledgeVersion();
        version.setKnowledgeId(knowledgeId);
        version.setVersionNo(versionNo);
        applyEditableFields(version, request, operatorId);
        version.setVersionStatus(versionStatus);
        version.setCreatedBy(operatorId);
        return version;
    }

    private void applyEditableFields(
            KnowledgeVersion version, KnowledgeSaveRequest request, String operatorId) {
        version.setTitle(StringUtils.trim(request.getTitle()));
        version.setContent(StringUtils.trim(request.getContent()));
        version.setTags(request.getTags() == null
                ? new String[0]
                : request.getTags().stream().map(StringUtils::trim).filter(StringUtils::isNotBlank)
                    .distinct().toArray(String[]::new));
        version.setIntentCode(StringUtils.trimToNull(request.getIntentCode()));
        version.setEffectiveAt(request.getEffectiveAt());
        version.setExpiredAt(request.getExpiredAt());
        version.setUpdatedBy(operatorId);
    }

    private int nextVersionNo(long knowledgeId) {
        return queryMapper.selectNextVersionNo(knowledgeId);
    }

    private void createApproval(
            Knowledge knowledge,
            KnowledgeVersion version,
            int actionType,
            KnowledgeSaveRequest request,
            String operatorId) {
        KnowledgeApproval approval = new KnowledgeApproval();
        approval.setApprovalNo("KA-" + compactUuid());
        approval.setKnowledgeId(knowledge.getId());
        approval.setVersionId(version.getId());
        approval.setActionType(actionType);
        approval.setStatus(KnowledgeCodes.APPROVAL_PENDING);
        approval.setApplicantId(operatorId);
        approval.setApplicationReason(StringUtils.trimToNull(request.getApplicationReason()));
        approval.setSubmittedAt(OffsetDateTime.now());
        approvalMapper.insert(approval);
    }

    /** 在版本提交审批的同一事务中保存人工确认的分片与标准问法。 */
    private void saveDrafts(
            Long knowledgeId,
            Long versionId,
            List<KnowledgeSaveRequest.ChunkDraft> drafts) {
        for (int chunkNo = 0; chunkNo < drafts.size(); chunkNo++) {
            KnowledgeSaveRequest.ChunkDraft draft = drafts.get(chunkNo);
            String content = StringUtils.trim(draft.getContent());
            KnowledgeChunk chunk = new KnowledgeChunk();
            chunk.setKnowledgeId(knowledgeId);
            chunk.setVersionId(versionId);
            chunk.setChunkNo(chunkNo);
            chunk.setChunkContent(content);
            chunk.setContentHash(sha256(content));
            chunk.setIndexVersion(1);
            chunk.setSyncStatus(KnowledgeCodes.CHUNK_PENDING);
            chunkMapper.insert(chunk);

            for (int questionNo = 0; questionNo < draft.getQuestions().size(); questionNo++) {
                String questionText = StringUtils.trim(draft.getQuestions().get(questionNo));
                KnowledgeQuestion question = new KnowledgeQuestion();
                question.setKnowledgeId(knowledgeId);
                question.setVersionId(versionId);
                question.setChunkId(chunk.getId());
                question.setQuestionNo(questionNo);
                question.setQuestionText(questionText);
                question.setQuestionHash(sha256(questionText));
                question.setSyncStatus(KnowledgeCodes.CHUNK_PENDING);
                questionMapper.insert(question);
            }
        }
    }

    /** 更新草稿时先清理该版本旧问法和旧分片，再按页面顺序重建。 */
    private void replaceDrafts(
            Long knowledgeId,
            Long versionId,
            List<KnowledgeSaveRequest.ChunkDraft> drafts) {
        questionMapper.delete(Wrappers.<KnowledgeQuestion>lambdaQuery()
                .eq(KnowledgeQuestion::getVersionId, versionId));
        chunkMapper.delete(Wrappers.<KnowledgeChunk>lambdaQuery()
                .eq(KnowledgeChunk::getVersionId, versionId));
        saveDrafts(knowledgeId, versionId, drafts);
    }

    /** 查询一个版本的分片和问法，供编辑抽屉回显。 */
    private List<KnowledgeChunkItem> loadChunks(Long versionId) {
        return chunkMapper.selectList(Wrappers.<KnowledgeChunk>lambdaQuery()
                        .eq(KnowledgeChunk::getVersionId, versionId)
                        .orderByAsc(KnowledgeChunk::getChunkNo))
                .stream()
                .map(chunk -> new KnowledgeChunkItem(
                        chunk.getId(),
                        chunk.getChunkNo(),
                        chunk.getChunkContent(),
                        questionMapper.selectList(Wrappers.<KnowledgeQuestion>lambdaQuery()
                                        .eq(KnowledgeQuestion::getChunkId, chunk.getId())
                                        .orderByAsc(KnowledgeQuestion::getQuestionNo))
                                .stream()
                                .map(KnowledgeQuestion::getQuestionText)
                                .toList()))
                .toList();
    }

    private String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("当前JDK不支持SHA-256", exception);
        }
    }
    private void validateRequest(KnowledgeSaveRequest request) {
        if (request.getExpiredAt() != null
                && !request.getExpiredAt().isAfter(request.getEffectiveAt())) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        if (request.getChunks() == null || request.getChunks().isEmpty()
                || request.getChunks().size() > 100
                || request.getChunks().stream().anyMatch(chunk ->
                        StringUtils.isBlank(chunk.getContent())
                                || chunk.getQuestions() == null
                                || chunk.getQuestions().isEmpty()
                                || chunk.getQuestions().size() > 8
                                || chunk.getQuestions().stream().anyMatch(StringUtils::isBlank))) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
    }

    private Knowledge requireKnowledge(long id) {
        Knowledge knowledge = knowledgeMapper.selectById(id);
        if (knowledge == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return knowledge;
    }

    private KnowledgeVersion requireVersion(long id) {
        KnowledgeVersion version = versionMapper.selectById(id);
        if (version == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return version;
    }

    private void requireCategory(long id) {
        KnowledgeCategory category = categoryMapper.selectById(id);
        if (category == null || !Integer.valueOf(1).equals(category.getStatus())) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
    }

    private void requireNoPendingVersion(Knowledge knowledge) {
        if (knowledge.getPendingVersionId() != null) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
    }

    private String normalizeView(String view) {
        String normalized = StringUtils.defaultIfBlank(view, "all").toLowerCase(Locale.ROOT);
        return List.of("all", "pending", "published", "disabled").contains(normalized)
                ? normalized : "all";
    }

    private String compactUuid() {
        return UUID.randomUUID().toString().replace("-", "").toUpperCase(Locale.ROOT);
    }
}
