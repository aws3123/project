package com.demo.ticket;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TicketController {
    private final TicketOrderService ticketOrderService;

    public TicketController(TicketOrderService ticketOrderService) {
        this.ticketOrderService = ticketOrderService;
    }

    @PostMapping("/tickets/order")
    public TicketOrder order(
            @RequestParam String userId,
            @RequestParam String showId,
            @RequestParam int ticketCount,
            @RequestParam(required = false) String couponCode
    ) {
        return ticketOrderService.submitOrder(userId, showId, ticketCount, couponCode);
    }
}
