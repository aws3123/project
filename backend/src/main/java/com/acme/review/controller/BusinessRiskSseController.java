package com.acme.review.controller;

import com.acme.review.dto.SseBusinessRiskEvent;
import com.acme.review.service.BusinessRiskSseService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/api/business-risk")
@RequiredArgsConstructor
public class BusinessRiskSseController {

    private final BusinessRiskSseService sseService;

    @GetMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> stream(
            @RequestParam("sessionId") String sessionId,
            @RequestParam(value = "lastEventId", required = false) String lastEventIdParam,
            @RequestHeader(value = "Last-Event-ID", required = false) String lastEventIdHeader
    ) {
        String lastEventId = (lastEventIdParam != null && !lastEventIdParam.isBlank())
                ? lastEventIdParam
                : lastEventIdHeader;
        Flux<SseBusinessRiskEvent> replay = sseService.replayFrom(sessionId, lastEventId);
        Flux<SseBusinessRiskEvent> live = sseService.liveStream(sessionId);
        return Flux.concat(replay, live).map(event -> ServerSentEvent.<String>builder()
                .id(event.getEventId())
                .event(event.getType())
                .data(event.getPayload())
                .build());
    }
}
