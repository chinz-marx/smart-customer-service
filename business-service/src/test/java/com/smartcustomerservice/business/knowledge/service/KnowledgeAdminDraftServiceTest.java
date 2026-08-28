package com.smartcustomerservice.business.knowledge.service;

import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeSaveRequest;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeApproval;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCategory;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeChunk;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeQuestion;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeApprovalMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeCategoryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeChunkMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQueryMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeQuestionMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class KnowledgeAdminDraftServiceTest {
    @Mock
    private KnowledgeMapper knowledgeMapper;
    @Mock
    private KnowledgeVersionMapper versionMapper;
    @Mock
    private KnowledgeCategoryMapper categoryMapper;
    @Mock
    private KnowledgeApprovalMapper approvalMapper;
    @Mock
    private KnowledgeQueryMapper queryMapper;
    @Mock
    private KnowledgeChunkMapper chunkMapper;
    @Mock
    private KnowledgeQuestionMapper questionMapper;

    @InjectMocks
    private KnowledgeAdminService service;

    @Test
    void saveDraftCreatesDraftWithoutApproval() {
        Knowledge knowledge = knowledge(1L, null);
        AtomicReference<KnowledgeVersion> savedVersion = new AtomicReference<>();
        stubDetail(knowledge, savedVersion);
        when(queryMapper.selectNextVersionNo(1L)).thenReturn(3);
        when(versionMapper.insert(any(KnowledgeVersion.class))).thenAnswer(invocation -> {
            KnowledgeVersion version = invocation.getArgument(0);
            version.setId(10L);
            savedVersion.set(version);
            return 1;
        });
        when(chunkMapper.insert(any(KnowledgeChunk.class))).thenAnswer(invocation -> {
            KnowledgeChunk chunk = invocation.getArgument(0);
            chunk.setId(20L);
            return 1;
        });

        service.saveDraft(1L, request(), "editor-001");

        assertThat(savedVersion.get().getVersionStatus()).isEqualTo(KnowledgeCodes.VERSION_DRAFT);
        assertThat(savedVersion.get().getVersionNo()).isEqualTo(3);
        assertThat(knowledge.getPendingVersionId()).isEqualTo(10L);
        verify(approvalMapper, never()).insert(any(KnowledgeApproval.class));
    }

    @Test
    void submitPromotesExistingDraftAndCreatesApproval() {
        Knowledge knowledge = knowledge(1L, 10L);
        KnowledgeVersion draft = new KnowledgeVersion();
        draft.setId(10L);
        draft.setKnowledgeId(1L);
        draft.setVersionNo(3);
        draft.setVersionStatus(KnowledgeCodes.VERSION_DRAFT);
        AtomicReference<KnowledgeVersion> savedVersion = new AtomicReference<>(draft);
        stubDetail(knowledge, savedVersion);
        when(chunkMapper.insert(any(KnowledgeChunk.class))).thenAnswer(invocation -> {
            KnowledgeChunk chunk = invocation.getArgument(0);
            chunk.setId(21L);
            return 1;
        });

        service.update(1L, request(), "editor-001");

        assertThat(draft.getVersionStatus()).isEqualTo(KnowledgeCodes.VERSION_PENDING);
        verify(versionMapper, never()).insert(any(KnowledgeVersion.class));
        verify(questionMapper).delete(any());
        verify(chunkMapper).delete(any());
        verify(approvalMapper).insert(any(KnowledgeApproval.class));
    }

    private void stubDetail(
            Knowledge knowledge,
            AtomicReference<KnowledgeVersion> savedVersion) {
        KnowledgeCategory category = new KnowledgeCategory();
        category.setId(2L);
        category.setCategoryName("退款规则");
        when(knowledgeMapper.selectById(1L)).thenReturn(knowledge);
        when(categoryMapper.selectById(2L)).thenReturn(category);
        when(versionMapper.selectById(10L)).thenAnswer(invocation -> savedVersion.get());
        when(approvalMapper.selectOne(any())).thenReturn(null);
        when(chunkMapper.selectList(any())).thenReturn(List.of());
    }

    private Knowledge knowledge(long id, Long pendingVersionId) {
        Knowledge knowledge = new Knowledge();
        knowledge.setId(id);
        knowledge.setCategoryId(2L);
        knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_ACTIVE);
        knowledge.setPendingVersionId(pendingVersionId);
        knowledge.setUpdatedBy("editor-001");
        return knowledge;
    }

    private KnowledgeSaveRequest request() {
        KnowledgeSaveRequest.ChunkDraft chunk = new KnowledgeSaveRequest.ChunkDraft();
        chunk.setContent("退款审核通过后通常在1至7个工作日内到账。");
        chunk.setQuestions(List.of("退款多久到账？"));

        KnowledgeSaveRequest request = new KnowledgeSaveRequest();
        request.setTitle("退款到账时间");
        request.setCategoryId(2L);
        request.setContent(chunk.getContent());
        request.setTags(List.of("退款", "到账"));
        request.setIntentCode("refund_request");
        request.setEffectiveAt(OffsetDateTime.now().minusMinutes(1));
        request.setChunks(List.of(chunk));
        request.setApplicationReason("调整退款说明");
        return request;
    }
}
