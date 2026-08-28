package com.smartcustomerservice.business.knowledge.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.knowledge.api.dto.KnowledgeReindexResult;
import com.smartcustomerservice.business.knowledge.domain.Knowledge;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeCodes;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOutboxEvent;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeVersion;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOutboxEventMapper;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeVersionMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class KnowledgeReindexServiceTest {
    @Mock
    private KnowledgeMapper knowledgeMapper;
    @Mock
    private KnowledgeVersionMapper versionMapper;
    @Mock
    private KnowledgeOutboxEventMapper outboxMapper;

    private KnowledgeReindexService service;

    @BeforeEach
    void setUp() {
        service = new KnowledgeReindexService(
                knowledgeMapper, versionMapper, outboxMapper, new ObjectMapper());
    }

    @Test
    void createsOutboxEventForCurrentPublishedVersion() {
        Knowledge knowledge = activeKnowledge();
        KnowledgeVersion version = publishedVersion();
        when(knowledgeMapper.selectList(any())).thenReturn(List.of(knowledge));
        when(versionMapper.selectById(11L)).thenReturn(version);
        when(outboxMapper.selectLatestUnfinishedUpsert(1L, 11L)).thenReturn(null);

        KnowledgeReindexResult result = service.reindexPublished("operator-1");

        assertThat(result).isEqualTo(new KnowledgeReindexResult(1, 0, 0));
        ArgumentCaptor<KnowledgeOutboxEvent> eventCaptor =
                ArgumentCaptor.forClass(KnowledgeOutboxEvent.class);
        verify(outboxMapper).insert(eventCaptor.capture());
        KnowledgeOutboxEvent event = eventCaptor.getValue();
        assertThat(event.getKnowledgeId()).isEqualTo(1L);
        assertThat(event.getVersionId()).isEqualTo(11L);
        assertThat(event.getStatus()).isEqualTo(KnowledgeCodes.OUTBOX_PENDING);
        assertThat(event.getPayload()).contains("manual-reindex", "operator-1");
    }

    @Test
    void resetsExistingFailedEventInsteadOfCreatingDuplicate() {
        Knowledge knowledge = activeKnowledge();
        KnowledgeVersion version = publishedVersion();
        KnowledgeOutboxEvent failed = new KnowledgeOutboxEvent();
        failed.setId(99L);
        failed.setStatus(KnowledgeCodes.OUTBOX_FAILED);
        failed.setRetryCount(4);
        failed.setLastError("temporary failure");
        when(knowledgeMapper.selectList(any())).thenReturn(List.of(knowledge));
        when(versionMapper.selectById(11L)).thenReturn(version);
        when(outboxMapper.selectLatestUnfinishedUpsert(1L, 11L)).thenReturn(failed);

        KnowledgeReindexResult result = service.reindexPublished("operator-2");

        assertThat(result).isEqualTo(new KnowledgeReindexResult(0, 1, 0));
        assertThat(failed.getStatus()).isEqualTo(KnowledgeCodes.OUTBOX_PENDING);
        assertThat(failed.getRetryCount()).isZero();
        assertThat(failed.getLastError()).isNull();
        verify(outboxMapper).updateById(failed);
    }

    @Test
    void skipsExpiredPublishedVersion() {
        Knowledge knowledge = activeKnowledge();
        KnowledgeVersion version = publishedVersion();
        version.setExpiredAt(OffsetDateTime.now().minusMinutes(1));
        when(knowledgeMapper.selectList(any())).thenReturn(List.of(knowledge));
        when(versionMapper.selectById(11L)).thenReturn(version);

        KnowledgeReindexResult result = service.reindexPublished("operator-3");

        assertThat(result).isEqualTo(new KnowledgeReindexResult(0, 0, 1));
    }

    private Knowledge activeKnowledge() {
        Knowledge knowledge = new Knowledge();
        knowledge.setId(1L);
        knowledge.setCurrentVersionId(11L);
        knowledge.setStatus(KnowledgeCodes.KNOWLEDGE_ACTIVE);
        return knowledge;
    }

    private KnowledgeVersion publishedVersion() {
        KnowledgeVersion version = new KnowledgeVersion();
        version.setId(11L);
        version.setKnowledgeId(1L);
        version.setVersionStatus(KnowledgeCodes.VERSION_PUBLISHED);
        version.setEffectiveAt(OffsetDateTime.now().minusMinutes(1));
        return version;
    }
}
