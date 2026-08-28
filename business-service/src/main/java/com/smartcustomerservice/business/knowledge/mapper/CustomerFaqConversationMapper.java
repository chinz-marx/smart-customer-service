package com.smartcustomerservice.business.knowledge.mapper;

import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqConversation;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/** FAQ直达回答使用与Python聊天主链路相同的会话和消息表。 */
@Mapper
public interface CustomerFaqConversationMapper {

    @Select("""
            SELECT id, session_id
            FROM public.chat_conversation
            WHERE id = #{conversationId} AND user_id = #{userId}
            """)
    CustomerFaqConversation selectById(
            @Param("conversationId") String conversationId,
            @Param("userId") String userId);

    @Select("""
            SELECT id, session_id
            FROM public.chat_conversation
            WHERE session_id = #{sessionId} AND user_id = #{userId}
            """)
    CustomerFaqConversation selectBySession(
            @Param("sessionId") String sessionId,
            @Param("userId") String userId);

    @Insert("""
            INSERT INTO public.chat_conversation (
                id, user_id, session_id, title, status, channel, created_at, updated_at
            ) VALUES (
                #{id}, #{userId}, #{sessionId}, #{title}, 'active', 'web', #{createdAt}, #{createdAt}
            )
            """)
    int insertConversation(
            @Param("id") String id,
            @Param("userId") String userId,
            @Param("sessionId") String sessionId,
            @Param("title") String title,
            @Param("createdAt") OffsetDateTime createdAt);

    @Update("""
            UPDATE public.chat_conversation
            SET updated_at = #{updatedAt}
            WHERE id = #{conversationId} AND user_id = #{userId}
            """)
    int touchConversation(
            @Param("conversationId") String conversationId,
            @Param("userId") String userId,
            @Param("updatedAt") OffsetDateTime updatedAt);

    @Insert("""
            INSERT INTO public.chat_message (
                id, conversation_id, role, content, request_id,
                intent, intent_confidence, provider, latency_ms, created_at
            ) VALUES (
                #{id}, #{conversationId}, #{role}, #{content}, #{requestId},
                #{intent}, #{intentConfidence}, #{provider}, #{latencyMs}, #{createdAt}
            )
            """)
    int insertMessage(
            @Param("id") String id,
            @Param("conversationId") String conversationId,
            @Param("role") String role,
            @Param("content") String content,
            @Param("requestId") String requestId,
            @Param("intent") String intent,
            @Param("intentConfidence") Double intentConfidence,
            @Param("provider") String provider,
            @Param("latencyMs") Double latencyMs,
            @Param("createdAt") OffsetDateTime createdAt);
}
